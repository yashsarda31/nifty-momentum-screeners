"""Liquid-glass Streamlit dashboard for scanner artifacts."""

from __future__ import annotations

import html
import json
from collections.abc import Callable, MutableMapping
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from nifty_vcp.breakouts import classify_high_rs_breakouts
from nifty_vcp.dashboard_support import (
    clear_startup_price_state,
    scan_freshness,
    scan_health_summary,
)
from nifty_vcp.models import RunStatus, ScanConfig
from nifty_vcp.pipeline import run_scan
from nifty_vcp.sessions import INDIA_TZ
from nifty_vcp.startup_prices import (
    StartupPriceSnapshot,
    attach_startup_prices,
    fetch_startup_prices,
)
from screener_ui import render_screeners
from watchlist_ui import render_tradingview_export

OUTPUT_ROOT = Path("outputs")
STARTUP_PRICES_KEY = "startup_prices"
ENRICHED_BUNDLE_KEY = "enriched_scan_bundle"
REQUIRED_RUN_FILES = (
    "run_manifest.json",
    "all_rankings.csv",
    "high_rs_setups.csv",
    "live_breakouts.csv",
    "exclusions.csv",
    "chart_history.csv.gz",
)


class RunBundleError(RuntimeError):
    """A published scan bundle cannot be loaded safely."""


def _validated_run_path(root: Path, run_directory: object) -> Path:
    if not isinstance(run_directory, str) or not run_directory.strip():
        raise RunBundleError("latest.json has no valid run_directory")
    resolved_root = root.resolve()
    candidate = (resolved_root / run_directory).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise RunBundleError("latest.json points outside the output root")
    missing = [name for name in REQUIRED_RUN_FILES if not (candidate / name).is_file()]
    if missing:
        raise RunBundleError(
            f"Published run {candidate.name} is missing {', '.join(missing)}"
        )
    return candidate


@st.cache_data(max_entries=2, show_spinner=False)
def _load_run_bundle(
    output_root: str,
    run_directory: str,
    pointer_version: int,
) -> dict:
    """Load one immutable published run; pointer_version invalidates the cache."""
    del pointer_version
    run_path = Path(output_root) / run_directory
    try:
        manifest = json.loads(
            (run_path / "run_manifest.json").read_text(encoding="utf-8")
        )
        chart_history = pd.read_csv(
            run_path / "chart_history.csv.gz", parse_dates=["date"]
        )
        bundle = {
            "path": run_path,
            "manifest": manifest,
            "rankings": pd.read_csv(run_path / "all_rankings.csv"),
            "setups": pd.read_csv(run_path / "high_rs_setups.csv"),
            "breakouts": pd.read_csv(run_path / "live_breakouts.csv"),
            "exclusions": pd.read_csv(run_path / "exclusions.csv"),
            "chart_history": chart_history,
            "screeners_available": False,
            "screeners_unavailable_reason": "This run predates expanded screeners.",
        }
        screener_files = {
            "selected_universe": "selected_universe.csv",
            "features": "screener_features.csv",
            "matches": "screener_matches.csv",
            "earnings": "earnings_events.csv",
        }
        if manifest.get("schema_version", 1) >= 2:
            missing = [
                filename
                for filename in screener_files.values()
                if not (run_path / filename).is_file()
            ]
            if missing:
                bundle["screeners_unavailable_reason"] = (
                    "This run is missing " + ", ".join(missing) + "."
                )
            else:
                for key, filename in screener_files.items():
                    bundle[key] = pd.read_csv(run_path / filename)
                earnings = bundle["earnings"]
                for column in ("event_date", "broadcast_at"):
                    if column in earnings:
                        earnings[column] = pd.to_datetime(
                            earnings[column], errors="coerce"
                        )
                earnings.attrs["status"] = manifest.get(
                    "earnings_status", "COMPLETE"
                )
                bundle["screeners_available"] = True
                bundle["screeners_unavailable_reason"] = ""
        return bundle
    except RunBundleError:
        raise
    except (OSError, ValueError, KeyError, pd.errors.ParserError) as exc:
        raise RunBundleError(
            f"Published run {run_directory} could not be read: {exc}"
        ) from exc


def load_latest_run(output_root: str | Path = OUTPUT_ROOT) -> dict | None:
    root = Path(output_root)
    pointer = root / "latest.json"
    if not pointer.exists():
        return None
    try:
        latest = json.loads(pointer.read_text(encoding="utf-8"))
        if not isinstance(latest, dict):
            raise RunBundleError("latest.json must contain a JSON object")
        run_path = _validated_run_path(root, latest.get("run_directory"))
        return _load_run_bundle(
            str(root.resolve()),
            run_path.name,
            pointer.stat().st_mtime_ns,
        )
    except RunBundleError:
        raise
    except (OSError, ValueError, KeyError, pd.errors.ParserError) as exc:
        raise RunBundleError(f"Could not read {pointer}: {exc}") from exc


def get_session_startup_prices(
    session_state: MutableMapping[str, Any],
    run_key: str,
    universe: pd.DataFrame,
    fetcher: Callable[[pd.DataFrame], StartupPriceSnapshot] = fetch_startup_prices,
) -> StartupPriceSnapshot:
    """Fetch once for a browser session and again when its scan bundle changes."""
    stored = session_state.get(STARTUP_PRICES_KEY)
    if stored is None or stored["run_key"] != run_key:
        stored = {"run_key": run_key, "snapshot": fetcher(universe)}
        session_state[STARTUP_PRICES_KEY] = stored
    return stored["snapshot"]


def _stored_histories(
    bundle: dict,
    symbols: set[str] | None = None,
) -> dict[str, pd.DataFrame]:
    history = bundle.get("chart_history", pd.DataFrame())
    required = {"symbol", "date", "High"}
    if history.empty or not required <= set(history.columns):
        return {}
    if symbols is not None:
        history = history.loc[history["symbol"].astype(str).isin(symbols)]
    histories = {}
    for symbol, frame in history.groupby("symbol", sort=False):
        data = frame.sort_values("date").copy()
        data["date"] = pd.to_datetime(data["date"])
        histories[str(symbol)] = data.set_index("date").drop(columns="symbol")
    return histories


def apply_startup_prices(
    bundle: dict, snapshot: StartupPriceSnapshot
) -> dict:
    """Enrich an in-memory bundle and reclassify live breakouts."""
    updated = dict(bundle)
    setups = bundle.get("setups", pd.DataFrame()).copy()
    setup_symbols = set(setups.get("symbol", pd.Series(dtype=str)).astype(str))
    histories = _stored_histories(bundle, setup_symbols)
    classifiable = setups[
        setups.get("symbol", pd.Series(dtype=str)).astype(str).isin(histories)
    ]
    if classifiable.empty:
        refreshed_setups = setups
    else:
        refreshed = classify_high_rs_breakouts(
            classifiable,
            histories,
            snapshot.quotes,
            int(bundle.get("manifest", {}).get("thresholds", {}).get("pivot_sessions", 55)),
        )
        missing = setups[
            ~setups.get("symbol", pd.Series(dtype=str)).astype(str).isin(histories)
        ]
        refreshed_setups = pd.concat([refreshed, missing], ignore_index=True)

    tables = {
        "rankings": bundle.get("rankings", pd.DataFrame()),
        "setups": refreshed_setups,
        "features": bundle.get("features", pd.DataFrame()),
    }
    for name, frame in tables.items():
        if not frame.empty and "symbol" in frame:
            updated[name] = attach_startup_prices(
                frame, snapshot.table, "latest_close"
            )
        else:
            updated[name] = frame.copy()
    setups_with_quotes = updated["setups"]
    if "is_breakout" in setups_with_quotes:
        updated["breakouts"] = setups_with_quotes[
            setups_with_quotes["is_breakout"].fillna(False).astype(bool)
        ].copy()
    else:
        updated["breakouts"] = setups_with_quotes.iloc[0:0].copy()
    updated["startup_prices"] = snapshot
    return updated


def get_session_enriched_bundle(
    session_state: MutableMapping[str, Any],
    run_key: str,
    bundle: dict,
    snapshot: StartupPriceSnapshot,
    enricher: Callable[[dict, StartupPriceSnapshot], dict] = apply_startup_prices,
) -> dict:
    """Apply a session's quote snapshot once instead of on every widget rerun."""
    snapshot_key = snapshot.fetched_at.isoformat()
    stored = session_state.get(ENRICHED_BUNDLE_KEY)
    if (
        stored is None
        or stored["run_key"] != run_key
        or stored["snapshot_key"] != snapshot_key
    ):
        stored = {
            "run_key": run_key,
            "snapshot_key": snapshot_key,
            "bundle": enricher(bundle, snapshot),
        }
        session_state[ENRICHED_BUNDLE_KEY] = stored
    return stored["bundle"]


def refresh_session_prices() -> None:
    """Discard this browser session's quote snapshot and fetch it on rerun."""
    clear_startup_price_state(
        st.session_state,
        STARTUP_PRICES_KEY,
        ENRICHED_BUNDLE_KEY,
    )
    st.rerun()


def startup_price_summary(snapshot: StartupPriceSnapshot) -> dict:
    """Summarize usable startup quote coverage for display."""
    table = snapshot.table
    total_count = len(table)
    latest = pd.to_numeric(table.get("latest_price"), errors="coerce")
    status = table.get("quote_status", pd.Series(index=table.index, dtype=str))
    usable_count = int(
        (latest.notna() & status.ne("UNAVAILABLE")).sum()
    )
    return {
        "fetched_at": snapshot.fetched_at.isoformat(),
        "usable_count": usable_count,
        "total_count": total_count,
        "coverage": usable_count / total_count if total_count else 0.0,
    }


def _startup_price_status(snapshot: StartupPriceSnapshot) -> None:
    summary = startup_price_summary(snapshot)
    st.caption(
        "Yahoo price snapshot "
        f"{summary['fetched_at']} · {summary['usable_count']} / "
        f"{summary['total_count']} symbols available · "
        "manual page refresh fetches again"
    )
    missing = summary["total_count"] - summary["usable_count"]
    if missing:
        st.warning(
            f"Latest Yahoo price unavailable for {missing} symbols. "
            "Their completed daily close remains visible separately."
        )


def render_vcp_stars(value: float) -> str:
    stars = max(0, min(5, int(value)))
    return f"{'★' * stars}{'☆' * (5 - stars)} ({stars} of 5)"


def render_stock_table(frame: pd.DataFrame) -> None:
    priority_columns = [
        column
        for column in (
            "symbol",
            "company_name",
            "latest_price",
            "quote_timestamp",
            "quote_status",
            "price_change_pct",
            "rs_rating",
            "vcp_stars",
            "latest_close",
            "price_date",
        )
        if column in frame
    ]
    table = frame[
        [*priority_columns, *(column for column in frame if column not in priority_columns)]
    ]
    column_config = {
        "latest_price": st.column_config.NumberColumn(
            "Latest Yahoo price", format="₹ %.2f"
        ),
        "quote_timestamp": st.column_config.DatetimeColumn(
            "Yahoo quote time", format="DD MMM, HH:mm:ss"
        ),
        "quote_status": "Quote status",
        "price_change_pct": st.column_config.NumberColumn(
            "Change vs scan close", format="%.2f%%"
        ),
        "vcp_stars": st.column_config.NumberColumn(
            "VCP rating",
            help="Rating out of 5. Click the column header to sort.",
            format="%d / 5",
            min_value=0,
            max_value=5,
        ),
        "latest_close": st.column_config.NumberColumn("Scan close", format="₹ %.2f"),
        "price_date": "Completed candle date",
    }
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={name: value for name, value in column_config.items() if name in table},
    )


def render_rs_leaders_table(leaders: pd.DataFrame) -> None:
    table = leaders.copy()
    table["vcp_stars"] = pd.to_numeric(table["vcp_stars"], errors="coerce").astype(
        "Int64"
    )
    render_stock_table(table)


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


def _render_scan_health(bundle: dict) -> None:
    manifest = bundle["manifest"]
    summary = scan_health_summary(manifest, bundle["exclusions"])
    if summary["status"] == RunStatus.INCOMPLETE.value:
        st.warning(
            "This scan is incomplete. Do not interpret missing matches as no signal."
        )

    columns = st.columns(2)
    columns[0].metric(
        "Historical coverage", f"{summary['historical_coverage']:.0%}"
    )
    columns[1].metric(
        "High-RS quote coverage", f"{summary['quote_coverage']:.0%}"
    )
    timing = "Duration unavailable"
    if summary["elapsed_seconds"] is not None:
        timing = f"{summary['elapsed_seconds'] / 60:.1f} minutes"
    st.caption(
        f"Started {summary['started_at'] or 'unknown'} · "
        f"Finished {summary['finished_at'] or 'unknown'} · "
        f"Market {summary['market_state']} · {timing}"
    )

    st.subheader("Provider status")
    st.dataframe(
        pd.DataFrame(
            {
                "Provider": summary["providers"].keys(),
                "Status": summary["providers"].values(),
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.subheader("Exclusions by reason")
    if summary["exclusion_groups"].empty:
        st.info("No exclusions were recorded.")
    else:
        st.dataframe(
            summary["exclusion_groups"], hide_index=True, width="stretch"
        )
    with st.expander("Full run manifest"):
        st.json(manifest)
    with st.expander("All exclusion rows"):
        st.dataframe(bundle["exclusions"], hide_index=True, width="stretch")


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
    feedback = st.session_state.pop("scan_feedback", None)
    if feedback:
        message = f"{feedback['outcome']} · Saved to {feedback['output_path']}"
        if feedback["status"] == RunStatus.COMPLETE.value:
            st.success(message)
        else:
            st.warning(message)

    with st.sidebar:
        st.subheader("Scanner control")
        if st.button("Run Live Scan", type="primary", width="stretch"):
            try:
                with st.spinner("Scanning the official universe…"):
                    summary = run_scan(ScanConfig(), output_root=OUTPUT_ROOT)
            except Exception as exc:  # noqa: BLE001 - keep the dashboard usable
                st.error(f"The scan could not be published: {exc}")
            else:
                st.session_state["scan_feedback"] = {
                    "status": summary.status.value,
                    "outcome": summary.outcome,
                    "output_path": str(summary.output_path),
                }
                clear_startup_price_state(
                    st.session_state,
                    STARTUP_PRICES_KEY,
                    ENRICHED_BUNDLE_KEY,
                )
                _load_run_bundle.clear()
                st.rerun()
        st.caption("Yahoo Finance may be delayed. Research use only; no orders are placed.")

    try:
        bundle = load_latest_run(OUTPUT_ROOT)
    except RunBundleError as exc:
        st.error(
            f"The latest stored scan cannot be read: {exc}. "
            "Run Live Scan to publish a new diagnostic bundle."
        )
        return
    if bundle is None:
        st.info("No scan yet. Use Run Live Scan to create the first local result.")
        return
    if bundle.get("screeners_available", False):
        with st.sidebar:
            if st.button(
                "Refresh Yahoo prices",
                icon=":material/refresh:",
                width="stretch",
                help="Fetch again for this browser session without running a full scan.",
            ):
                refresh_session_prices()
        with st.spinner("Fetching the latest Yahoo prices..."):
            snapshot = get_session_startup_prices(
                st.session_state,
                str(bundle["path"]),
                bundle["selected_universe"],
            )
        bundle = get_session_enriched_bundle(
            st.session_state,
            str(bundle["path"]),
            bundle,
            snapshot,
        )
    manifest = bundle["manifest"]
    status = str(manifest.get("status", "UNKNOWN"))
    freshness = scan_freshness(manifest, datetime.now(tz=INDIA_TZ))
    st.markdown(
        status_badge(status)
        + f" <span class='footnote'>As of {html.escape(str(manifest.get('finished_at', 'unknown')))} · "
        + f"Market {html.escape(str(manifest.get('market_state', 'unknown')))}</span>",
        unsafe_allow_html=True,
    )
    st.caption(f"Stored daily scan: {freshness.label}")
    if freshness.is_stale:
        st.warning(
            "Stored daily scan results are stale. Newer Yahoo prices do not refresh "
            "the completed-candle screener signals; run a new live scan before acting."
        )
    if "startup_prices" in bundle:
        _startup_price_status(bundle["startup_prices"])
    _metric_cards(manifest)
    tabs = st.tabs(
        [
            "Live Breakouts",
            "RS Leaders",
            "All Stocks",
            "Scan Health",
            "Methodology",
            "Screeners",
            "TV Top 25",
        ],
        key="main_tabs",
        on_change="rerun",
    )
    if tabs[0].open:
        with tabs[0]:
            if bundle["breakouts"].empty:
                st.info(manifest.get("outcome", "No breakout result available."))
            else:
                render_stock_table(bundle["breakouts"])
            _stock_detail(bundle)
    if tabs[1].open:
        with tabs[1]:
            search = st.text_input("Search high-RS stocks", key="leader_search")
            leaders = bundle["setups"]
            if search:
                leaders = leaders[
                    leaders.astype(str).apply(
                        lambda row: row.str.contains(search, case=False).any(), axis=1
                    )
                ]
            render_rs_leaders_table(leaders)
    if tabs[2].open:
        with tabs[2]:
            render_stock_table(bundle["rankings"])
    if tabs[3].open:
        with tabs[3]:
            _render_scan_health(bundle)
    if tabs[4].open:
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
    if tabs[5].open:
        with tabs[5]:
            render_screeners(bundle)
    if tabs[6].open:
        with tabs[6]:
            render_tradingview_export(
                bundle.get("features", pd.DataFrame()),
                bundle.get("selected_universe", pd.DataFrame()),
            )


if __name__ == "__main__":
    main()
