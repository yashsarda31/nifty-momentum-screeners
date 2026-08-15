"""TradingView watchlist selection and export helpers."""

from __future__ import annotations

import pandas as pd

WATCHLIST_COLUMNS = [
    "rank",
    "symbol",
    "tradingview_symbol",
    "company_name",
    "rs_rating",
    "vcp_stars",
    "median_traded_value_60d",
]


def build_tradingview_watchlist(
    features: pd.DataFrame,
    selected_universe: pd.DataFrame | None = None,
    minimum_traded_value: float = 100_000_000,
    limit: int = 25,
) -> pd.DataFrame:
    required = {
        "symbol",
        "rs_rating",
        "vcp_stars",
        "median_traded_value_60d",
        "top_1000_liquid",
        "is_high_rs",
        "history_status",
    }
    if features.empty or not required <= set(features.columns) or limit <= 0:
        return pd.DataFrame(columns=WATCHLIST_COLUMNS)

    ranked = features.copy()
    if (
        selected_universe is not None
        and {"symbol", "median_traded_value_60d"} <= set(selected_universe.columns)
    ):
        liquidity_by_symbol = (
            selected_universe.drop_duplicates("symbol", keep="first")
            .set_index("symbol")["median_traded_value_60d"]
        )
        ranked["median_traded_value_60d"] = ranked[
            "median_traded_value_60d"
        ].fillna(ranked["symbol"].map(liquidity_by_symbol))
    for column in ("rs_rating", "vcp_stars", "median_traded_value_60d"):
        ranked[column] = pd.to_numeric(ranked[column], errors="coerce")
    top_1000 = (
        ranked["top_1000_liquid"]
        .fillna(False)
        .astype(str)
        .str.lower()
        .isin({"true", "1"})
    )
    high_rs = (
        ranked["is_high_rs"]
        .fillna(False)
        .astype(str)
        .str.lower()
        .isin({"true", "1"})
    )
    complete = ranked["history_status"].astype(str).str.upper().eq("COMPLETE")
    ranked = ranked.loc[
        top_1000
        & high_rs
        & complete
        & ranked["median_traded_value_60d"].ge(minimum_traded_value)
        & ranked["rs_rating"].notna()
        & ranked["vcp_stars"].notna()
    ].copy()
    ranked["symbol"] = ranked["symbol"].astype(str).str.strip().str.upper()
    ranked = ranked.loc[ranked["symbol"].ne("")]
    ranked = ranked.sort_values(
        ["rs_rating", "vcp_stars", "median_traded_value_60d", "symbol"],
        ascending=[False, False, False, True],
        kind="stable",
    ).head(limit)
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    ranked.insert(2, "tradingview_symbol", "NSE:" + ranked["symbol"])
    if "company_name" not in ranked:
        ranked["company_name"] = ""
    return ranked[WATCHLIST_COLUMNS].reset_index(drop=True)


def format_tradingview_watchlist(watchlist: pd.DataFrame) -> str:
    if watchlist.empty or "tradingview_symbol" not in watchlist:
        return ""
    symbols = watchlist["tradingview_symbol"].dropna().astype(str).str.strip()
    return ",".join(symbols.loc[symbols.ne("")].drop_duplicates())
