"""Liquid-glass Streamlit dashboard for scanner artifacts."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from nifty_vcp.models import ScanConfig
from nifty_vcp.pipeline import run_scan
from screener_ui import render_screeners

OUTPUT_ROOT = Path("outputs")


def load_latest_run(output_root: str | Path = OUTPUT_ROOT) -> dict | None:
    root = Path(output_root)
    pointer = root / "latest.json"
    if not pointer.exists():
        return None
    latest = json.loads(pointer.read_text(encoding="utf-8"))
    run_path = root / latest["run_directory"]
    manifest = json.loads((run_path / "run_manifest.json").read_text(encoding="utf-8"))
    chart_history = pd.read_csv(run_path / "chart_history.csv.gz", parse_dates=["date"])
    bundle = {
        "path": run_path,
        "manifest": manifest,
        "rankings": pd.read_csv(run_path / "all_rankings.csv"),
        "setups": pd.read_csv(run_path / "high_rs_setups.csv"),
        "breakouts": pd.read_csv(run_path / "live_breakouts.csv"),
        "exclusions": pd.read_csv(run_path / "exclusions.csv"),
        "chart_history": chart_history,
        "screeners_available": False,
    }
    screener_files = {
        "selected_universe": "selected_universe.csv",
        "features": "screener_features.csv",
        "matches": "screener_matches.csv",
        "earnings": "earnings_events.csv",
    }
    if manifest.get("schema_version", 1) >= 2 and all(
        (run_path / filename).exists() for filename in screener_files.values()
    ):
        for key, filename in screener_files.items():
            bundle[key] = pd.read_csv(run_path / filename)
        earnings = bundle["earnings"]
        for column in ("event_date", "broadcast_at"):
            if column in earnings:
                earnings[column] = pd.to_datetime(earnings[column], errors="coerce")
        earnings.attrs["status"] = manifest.get("earnings_status", "COMPLETE")
        bundle["screeners_available"] = True
    return bundle


def render_vcp_stars(value: float) -> str:
    stars = max(0, min(5, int(value)))
    return f"{'★' * stars}{'☆' * (5 - stars)} ({stars} of 5)"


def status_badge(status: str) -> str:
    safe = html.escape(status)
    css_class = "incomplete" if "INCOMPLETE" in status.upper() else "complete"
    return f'<span class="status-badge {css_class}">{safe}</span>'


def build_price_figure(frame: pd.DataFrame, pivot: float) -> go.Figure:
    data = frame.sort_values("date").copy()
    for sessions in (50, 150, 200):
        data[f"SMA {sessions}"] = data["Close"].rolling(sessions).mean()
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.76, 0.24],
    )
    figure.add_trace(
        go.Candlestick(
            x=data["date"],
            open=data["Open"],
            high=data["High"],
            low=data["Low"],
            close=data["Close"],
            name="Price",
        ),
        row=1,
        col=1,
    )
    colors = {50: "#79e8ff", 150: "#a995ff", 200: "#ffd27a"}
    for sessions in (50, 150, 200):
        figure.add_trace(
            go.Scatter(
                x=data["date"],
                y=data[f"SMA {sessions}"],
                name=f"SMA {sessions}",
                line={"width": 1.5, "color": colors[sessions]},
            ),
            row=1,
            col=1,
        )
    figure.add_trace(
        go.Bar(x=data["date"], y=data["Volume"], name="Volume", marker_color="#6c7fa8"),
        row=2,
        col=1,
    )
    figure.add_hline(
        y=pivot,
        line_dash="dot",
        line_color="#70f2b0",
        annotation_text="55-session pivot",
        row=1,
        col=1,
    )
    figure.update_layout(
        height=650,
        margin={"l": 16, "r": 16, "t": 30, "b": 16},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#f7f9ff"},
        xaxis_rangeslider_visible=False,
        legend={"orientation": "h", "y": 1.04},
    )
    figure.update_xaxes(gridcolor="rgba(255,255,255,.06)")
    figure.update_yaxes(gridcolor="rgba(255,255,255,.06)")
    return figure


def build_vcp_evidence(setup: pd.Series) -> pd.DataFrame:
    component_columns = [column for column in setup.index if column.startswith("vcp_")]
    return pd.DataFrame(
        {
            "criterion": component_columns,
            "value": [str(setup[column]) for column in component_columns],
        }
    )


def _metric_cards(manifest: dict) -> None:
    columns = st.columns(4)
    columns[0].metric(
        "History coverage",
        f"{manifest.get('historical_coverage', 0):.0%}",
        f"{manifest.get('valid_history_count', 0)} / {manifest.get('universe_count', 0)}",
    )
    columns[1].metric("High RS", manifest.get("high_rs_count", 0), "RS 80+")
    columns[2].metric("Live breakouts", manifest.get("breakout_count", 0))
    columns[3].metric(
        "Quote coverage", f"{manifest.get('quote_coverage', 0):.0%}"
    )


def _stock_detail(bundle: dict) -> None:
    setups = bundle["setups"]
    if setups.empty:
        st.info("No high-RS setups are available in this run.")
        return
    symbol = st.selectbox("Inspect setup", setups["symbol"].astype(str).tolist())
    setup = setups.loc[setups["symbol"].astype(str) == symbol].iloc[0]
    st.markdown(
        f'<div class="star-rating">{render_vcp_stars(setup.get("vcp_stars", 0))}</div>',
        unsafe_allow_html=True,
    )
    history = bundle["chart_history"]
    history = history[history["symbol"].astype(str) == symbol]
    required = {"date", "Open", "High", "Low", "Close", "Volume"}
    if history.empty or not required <= set(history.columns):
        st.warning("Stored chart history is unavailable for this symbol.")
        return
    st.plotly_chart(
        build_price_figure(history, float(setup.get("pivot_55", history["High"].tail(55).max()))),
        width="stretch",
        config={"displaylogo": False},
    )
    st.dataframe(build_vcp_evidence(setup), width="stretch", hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Nifty Momentum Glass", page_icon="◈", layout="wide")
    css = (Path(__file__).parent / "assets" / "liquid_glass.css").read_text(
        encoding="utf-8"
    )
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    st.markdown(
        """
        <section class="hero">
          <div class="eyebrow">Nifty Total Market · Live research surface</div>
          <h1>Momentum, in focus.</h1>
          <p>Cross-sectional relative strength, strict 55-session breakouts, and a transparent five-star VCP lens.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    with st.sidebar:
        st.subheader("Scanner control")
        if st.button("Run Live Scan", type="primary", width="stretch"):
            with st.spinner("Scanning the official universe…"):
                run_scan(ScanConfig(), output_root=OUTPUT_ROOT)
            st.rerun()
        st.caption("Yahoo Finance may be delayed. Research use only; no orders are placed.")

    bundle = load_latest_run(OUTPUT_ROOT)
    if bundle is None:
        st.info("No scan yet. Use Run Live Scan to create the first local result.")
        return
    manifest = bundle["manifest"]
    status = str(manifest.get("status", "UNKNOWN"))
    st.markdown(
        status_badge(status)
        + f" <span class='footnote'>As of {html.escape(str(manifest.get('finished_at', 'unknown')))} · "
        + f"Market {html.escape(str(manifest.get('market_state', 'unknown')))}</span>",
        unsafe_allow_html=True,
    )
    _metric_cards(manifest)
    tabs = st.tabs(
        [
            "Live Breakouts",
            "RS Leaders",
            "All Stocks",
            "Scan Health",
            "Methodology",
            "Screeners",
        ],
        key="main_tabs",
        on_change="rerun",
    )
    with tabs[0]:
        if bundle["breakouts"].empty:
            st.info(manifest.get("outcome", "No breakout result available."))
        else:
            st.dataframe(bundle["breakouts"], width="stretch", hide_index=True)
        _stock_detail(bundle)
    with tabs[1]:
        search = st.text_input("Search high-RS stocks", key="leader_search")
        leaders = bundle["setups"]
        if search:
            leaders = leaders[
                leaders.astype(str).apply(
                    lambda row: row.str.contains(search, case=False).any(), axis=1
                )
            ]
        st.dataframe(leaders, width="stretch", hide_index=True)
    with tabs[2]:
        st.dataframe(bundle["rankings"], width="stretch", hide_index=True)
    with tabs[3]:
        st.json(manifest)
        st.dataframe(bundle["exclusions"], width="stretch", hide_index=True)
    with tabs[4]:
        st.markdown(
            """
            **Relative strength:** 40% of 63-session return plus 20% each of
            126-, 189-, and 252-session returns, percentile-ranked 1–99.

            **Breakout:** latest valid one-minute price strictly above the highest
            completed-session high from the prior 55 sessions. Delayed or closed-market
            observations cannot confirm a live breakout.

            **VCP stars:** trend template, 52-week position, contracting price ranges,
            contracting ATR%, and pivot readiness with volume dry-up. This is a
            transparent Minervini-inspired approximation, not an official proprietary score.
            """
        )
    with tabs[5]:
        render_screeners(bundle)


if __name__ == "__main__":
    main()
