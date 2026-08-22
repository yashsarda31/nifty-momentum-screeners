"""Streamlit UI for preset, multiple-scan, and local custom screeners."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from nifty_vcp.custom_screeners import (
    CustomScreener,
    Rule,
    delete_screener,
    evaluate_custom,
    load_store,
    rename_screener,
    save_screener,
)
from nifty_vcp.screeners import (
    SCREENER_CATALOG,
    default_thresholds,
    evaluate_all_screeners,
    evaluate_screener,
    multiple_scan_matches,
)
from watchlist_ui import render_screen_results_export

MENU_ITEMS = (
    "Create/load screener",
    "Multiple scans",
    "Horizontal resistance",
    "Tight setup",
    "IPO scanner",
    "RS high before price high",
    "Momentum scanner",
    "Volume screeners",
    "VCP",
    "Flags & pennants",
    "Earnings screeners",
    "Gap screeners",
    "Inside bar",
)
RESULT_STATES = (
    "MATCH",
    "All states",
    "NO MATCH",
    "NOT ELIGIBLE",
    "SCAN INCOMPLETE",
)


def _key(label: str) -> str:
    return "screen_" + label.lower().replace(" & ", "_").replace("/", "_").replace(
        " ", "_"
    )


def _select_menu(item: str) -> None:
    st.session_state["screener_menu"] = item


def _category_slugs(category: str) -> list[str]:
    return [
        slug
        for slug, definition in SCREENER_CATALOG.items()
        if definition.category == category
    ]


def filter_preset_results(
    slug: str,
    features: pd.DataFrame,
    events: pd.DataFrame,
    thresholds: Mapping[str, Any],
) -> pd.DataFrame:
    """Re-evaluate a preset locally from stored evidence."""
    return evaluate_screener(slug, features, events, thresholds)


def filter_result_view(
    results: pd.DataFrame,
    query: str,
    state: str,
) -> pd.DataFrame:
    """Filter stored results without recomputing any market-data evidence."""
    visible = results.copy()
    if visible.empty:
        return visible
    if state != "All states" and "state" in visible:
        visible = visible.loc[visible["state"].astype(str).eq(state)]
    needle = query.strip()
    if needle:
        symbol = visible.get("symbol", pd.Series("", index=visible.index)).astype(str)
        company = visible.get(
            "company_name", pd.Series("", index=visible.index)
        ).astype(str)
        mask = symbol.str.contains(
            needle, case=False, regex=False
        ) | company.str.contains(needle, case=False, regex=False)
        visible = visible.loc[mask]
    return visible.copy()


def selected_result_symbol(event: Mapping, frame: pd.DataFrame) -> str | None:
    selection = event.get("selection", {}) if event else {}
    rows = selection.get("rows", []) if isinstance(selection, Mapping) else []
    if not rows or rows[0] >= len(frame):
        return None
    return str(frame.iloc[rows[0]]["symbol"])


def result_display_columns(results: pd.DataFrame) -> list[str]:
    """Return a stable, user-facing order for screener result columns."""
    return [
        name
        for name in (
            "symbol",
            "company_name",
            "state",
            "reason",
            "latest_price",
            "quote_timestamp",
            "quote_status",
            "price_change_pct",
            "price_date",
            "liquidity_rank",
            "matched_screeners",
            "match_count",
        )
        if name in results
    ]


def _threshold_form(slug: str) -> dict[str, Any]:
    defaults = default_thresholds(slug)
    values: dict[str, Any] = {}
    with st.form(f"thresholds_{slug}"):
        for name, default in defaults.items():
            label = name.replace("_", " ").capitalize()
            if isinstance(default, bool):
                values[name] = st.checkbox(
                    label, value=default, key=f"threshold_{slug}_{name}"
                )
            elif isinstance(default, int):
                values[name] = st.number_input(
                    label,
                    value=default,
                    step=1,
                    key=f"threshold_{slug}_{name}",
                )
            else:
                values[name] = st.number_input(
                    label,
                    value=float(default),
                    step=0.1,
                    key=f"threshold_{slug}_{name}",
                )
        st.form_submit_button("Apply thresholds", width="stretch")
    return values


def _result_metrics(results: pd.DataFrame) -> None:
    counts = results["state"].value_counts() if "state" in results else pd.Series()
    columns = st.columns(4)
    columns[0].metric("Matches", int(counts.get("MATCH", 0)))
    columns[1].metric("No match", int(counts.get("NO MATCH", 0)))
    columns[2].metric("Not eligible", int(counts.get("NOT ELIGIBLE", 0)))
    columns[3].metric("Incomplete", int(counts.get("SCAN INCOMPLETE", 0)))


def _stock_detail(symbol: str, results: pd.DataFrame, bundle: dict) -> None:
    row = results.loc[results["symbol"].astype(str).eq(symbol)].iloc[0]
    st.subheader(f"{symbol} evidence")
    if "reason" in row:
        st.caption(str(row["reason"]))
    if "evidence" in row and pd.notna(row["evidence"]):
        try:
            st.json(json.loads(str(row["evidence"])))
        except json.JSONDecodeError:
            st.code(str(row["evidence"]))
    history = bundle.get("chart_history", pd.DataFrame())
    history = history.loc[history.get("symbol", pd.Series(dtype=str)).astype(str).eq(symbol)]
    required = {"date", "Open", "High", "Low", "Close", "Volume"}
    if history.empty or not required <= set(history):
        return
    from app import build_price_figure

    pivot = float(history["High"].tail(55).max())
    st.plotly_chart(
        build_price_figure(history, pivot),
        width="stretch",
        config={"displaylogo": False},
    )


def _render_results(results: pd.DataFrame, bundle: dict) -> pd.DataFrame:
    if results.empty:
        st.info("No eligible symbols are stored in this scan.")
        return results
    _result_metrics(results)
    if "state" in results and results["state"].astype(str).eq(
        "SCAN INCOMPLETE"
    ).any():
        st.warning(
            "Some rows are SCAN INCOMPLETE. Review them before treating missing "
            "matches as no signal."
        )
    filters = st.container(horizontal=True)
    query = filters.text_input(
        "Search symbol or company",
        key="screener_result_search",
    )
    state = filters.selectbox(
        "Result state",
        RESULT_STATES,
        key="screener_result_state",
    )
    visible = filter_result_view(results, query, state)
    if visible.empty:
        st.info("No rows match these filters.")
        return visible
    display_columns = result_display_columns(visible)
    display = visible.loc[:, display_columns].copy()
    event = st.dataframe(
        display,
        key="screener_results",
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        column_config={
            "latest_price": st.column_config.NumberColumn(
                "Latest Yahoo price", format="₹ %.2f"
            ),
            "price_change_pct": st.column_config.NumberColumn(
                "Change", format="%.2f%%"
            ),
            "quote_timestamp": st.column_config.DatetimeColumn(
                "Yahoo quote time", format="DD MMM, HH:mm:ss"
            ),
            "price_date": "Completed candle date",
        },
    )
    symbol = selected_result_symbol(event, display)
    if symbol:
        _stock_detail(symbol, visible, bundle)
    return visible


def _parse_rule_value(value: Any) -> float | str:
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        return text


def _render_custom(bundle: dict, store_path: Path) -> pd.DataFrame:
    features = bundle["features"]
    results = pd.DataFrame()
    try:
        store = load_store(store_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Custom screener store could not be loaded: {exc}")
        return results

    st.subheader("Create or load a screener")
    if store:
        selected_name = st.selectbox(
            "Saved screener", list(store), key="saved_custom_screener"
        )
        results = evaluate_custom(store[selected_name], features)
        results = _render_results(results, bundle)
        rename_to = st.text_input("Rename to", key="custom_rename_to")
        action_columns = st.columns(2)
        if action_columns[0].button("Rename", key="rename_custom", width="stretch"):
            try:
                rename_screener(store_path, selected_name, rename_to)
                st.rerun()
            except (KeyError, FileExistsError, ValueError) as exc:
                st.error(str(exc))
        if action_columns[1].button("Delete", key="delete_custom", width="stretch"):
            delete_screener(store_path, selected_name)
            st.rerun()
    else:
        st.info("No custom screeners saved yet.")

    fields = [
        name
        for name in features.columns
        if name not in {"symbol", "company_name", "price_date", "scan_date"}
    ]
    if not fields:
        return results
    with st.form("create_custom_screener"):
        name = st.text_input("Screener name", key="custom_name")
        rules = st.data_editor(
            pd.DataFrame(
                [
                    {"field": fields[0], "operator": ">=", "value": "0"},
                    {"field": fields[0], "operator": ">=", "value": "0"},
                ]
            ),
            key="custom_rule_editor",
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "field": st.column_config.SelectboxColumn("Field", options=fields),
                "operator": st.column_config.SelectboxColumn(
                    "Operator", options=[">", ">=", "<", "<=", "==", "!="]
                ),
            },
        )
        overwrite = st.checkbox("Overwrite a saved screener with this name")
        submitted = st.form_submit_button("Save screener", width="stretch")
    if submitted:
        try:
            parsed = tuple(
                Rule(str(row.field), str(row.operator), _parse_rule_value(row.value))
                for row in rules.itertuples(index=False)
                if str(row.field).strip()
            )
            save_screener(store_path, CustomScreener(name, parsed), overwrite)
            st.rerun()
        except (FileExistsError, TypeError, ValueError, OSError) as exc:
            st.error(str(exc))
    return results


def _render_multiple(bundle: dict) -> pd.DataFrame:
    options = {definition.label: slug for slug, definition in SCREENER_CATALOG.items()}
    with st.form("multiple_scans"):
        labels = st.multiselect("Preset screeners", list(options), key="multiple_presets")
        minimum = st.number_input(
            "Minimum matches", min_value=1, value=2, step=1, key="minimum_matches"
        )
        submitted = st.form_submit_button("Run multiple scans", width="stretch")
    if not submitted:
        st.caption("Choose two or more presets and the minimum number of matches.")
        return pd.DataFrame()
    if not labels:
        st.warning("Select at least one preset.")
        return pd.DataFrame()
    slugs = [options[label] for label in labels]
    all_results = evaluate_all_screeners(bundle["features"], bundle["earnings"])
    results = multiple_scan_matches(all_results, slugs, int(minimum))
    return _render_results(results, bundle)


def _render_preset(category: str, bundle: dict) -> pd.DataFrame:
    slugs = _category_slugs(category)
    labels = {SCREENER_CATALOG[slug].label: slug for slug in slugs}
    label = st.selectbox("Screener", list(labels), key="screener_preset")
    slug = labels[label]
    st.caption(SCREENER_CATALOG[slug].description)
    thresholds = _threshold_form(slug)
    results = filter_preset_results(
        slug, bundle["features"], bundle["earnings"], thresholds
    )
    return _render_results(results, bundle)


def render_screeners(
    bundle: dict, custom_store_path: Path = Path("custom_screeners.json")
) -> None:
    """Render the separate screener workspace using only stored scan artifacts."""
    if not bundle.get("screeners_available", False):
        reason = bundle.get(
            "screeners_unavailable_reason", "Run a new expanded scan."
        )
        st.info(
            "Screeners require a new expanded scan. "
            f"Existing results remain readable. {reason}"
        )
        return
    st.caption(
        "Completed daily bars only. Missing history is shown as NOT ELIGIBLE; "
        "provider gaps are SCAN INCOMPLETE."
    )
    menu, content = st.columns([0.28, 0.72], gap="large")
    active = st.session_state.get("screener_menu", "Horizontal resistance")
    screen_results = pd.DataFrame()
    with menu, st.container(border=True):
        for item in MENU_ITEMS:
            st.button(
                item,
                key=_key(item),
                width="stretch",
                on_click=_select_menu,
                args=(item,),
            )
    with content, st.container(border=True):
        st.header(active)
        if active == "Create/load screener":
            screen_results = _render_custom(bundle, custom_store_path)
        elif active == "Multiple scans":
            screen_results = _render_multiple(bundle)
        else:
            screen_results = _render_preset(active, bundle)
    st.divider()
    render_screen_results_export(screen_results)
