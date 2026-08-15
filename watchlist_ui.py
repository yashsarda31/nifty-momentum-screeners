"""Streamlit presentation for TradingView watchlist exports."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from nifty_vcp.watchlist import (
    build_tradingview_watchlist,
    format_tradingview_watchlist,
)


def render_tradingview_export(
    features: pd.DataFrame, selected_universe: pd.DataFrame | None = None
) -> None:
    st.subheader("TradingView Top 25")
    minimum_crore = st.number_input(
        "Minimum 60-session median traded value (₹ crore)",
        min_value=0.0,
        value=10.0,
        step=1.0,
        key="tradingview_minimum_crore",
        help="Close × volume; ₹10 crore means ₹100 million traded per day.",
    )
    watchlist = build_tradingview_watchlist(
        features,
        selected_universe,
        minimum_traded_value=float(minimum_crore) * 10_000_000,
    )
    st.caption(
        "Complete high-RS names from the top-1,000 liquidity universe, ranked by "
        "RS rating, VCP rating, then liquidity. Use the copy icon or import the TXT file."
    )
    if watchlist.empty:
        st.info("No eligible names meet this liquidity threshold in the latest scan.")
        return

    display = watchlist[
        [
            "rank",
            "symbol",
            "company_name",
            "rs_rating",
            "vcp_stars",
            "median_traded_value_60d",
        ]
    ].copy()
    display["median_traded_value_60d"] /= 10_000_000
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={
            "rank": st.column_config.NumberColumn("Rank", format="%d"),
            "symbol": "NSE symbol",
            "company_name": "Company",
            "rs_rating": st.column_config.NumberColumn("RS rating", format="%d"),
            "vcp_stars": st.column_config.NumberColumn(
                "VCP rating", format="%d / 5", min_value=0, max_value=5
            ),
            "median_traded_value_60d": st.column_config.NumberColumn(
                "60-day traded value", format="₹ %.1f cr"
            ),
        },
    )
    tradingview_text = format_tradingview_watchlist(watchlist)
    st.code(tradingview_text, language=None, wrap_lines=True)
    st.download_button(
        label="Download TradingView watchlist",
        data=tradingview_text,
        file_name="nifty_top25_tradingview.txt",
        mime="text/plain",
        icon=":material/download:",
        on_click="ignore",
    )
