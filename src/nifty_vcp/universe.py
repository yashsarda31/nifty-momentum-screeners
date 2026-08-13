"""Official NSE equity universe loading and scan-universe selection."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

import numpy as np
import pandas as pd
import requests

from nifty_vcp.models import ScanConfig

UNIVERSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
USER_AGENT = "Mozilla/5.0 (compatible; NiftyVCPResearch/0.2)"


def _column(aliases: dict[str, str], *names: str) -> str | None:
    return next((aliases[name] for name in names if name in aliases), None)


def parse_universe_csv(content: bytes) -> pd.DataFrame:
    frame = pd.read_csv(BytesIO(content))
    frame.columns = [str(column).strip() for column in frame.columns]
    aliases = {column.lower(): column for column in frame.columns}
    symbol_column = _column(aliases, "symbol")
    company_column = _column(aliases, "name of company", "company name", "company_name")
    series_column = _column(aliases, "series")
    listing_column = _column(aliases, "date of listing", "listing date")
    isin_column = _column(aliases, "isin number", "isin")
    if not all(
        (symbol_column, company_column, series_column, listing_column, isin_column)
    ):
        raise ValueError(
            "universe must contain symbol, company, series, listing date, and ISIN"
        )
    frame = frame[frame[series_column].astype(str).str.strip().str.upper().eq("EQ")]
    symbols = frame[symbol_column].astype(str).str.strip().str.upper()
    if symbols.eq("").any() or symbols.duplicated().any():
        duplicates = sorted(symbols[symbols.duplicated(keep=False)].unique())
        suffix = f": {', '.join(duplicates[:5])}" if duplicates else ""
        raise ValueError(f"duplicate symbols{suffix}")
    listing_dates = pd.to_datetime(
        frame[listing_column].astype(str).str.strip(), format="%d-%b-%Y", errors="coerce"
    )
    if listing_dates.isna().any():
        raise ValueError("universe contains invalid listing dates")
    industry_column = _column(aliases, "industry")
    industry = (
        frame[industry_column].astype(str).str.strip()
        if industry_column
        else pd.Series("", index=frame.index, dtype="string")
    )
    return pd.DataFrame(
        {
            "symbol": symbols,
            "company_name": frame[company_column].astype(str).str.strip(),
            "industry": industry,
            "series": "EQ",
            "isin": frame[isin_column].astype(str).str.strip(),
            "listing_date": listing_dates,
            "yahoo_symbol": symbols + ".NS",
        }
    ).reset_index(drop=True)


def fetch_universe(
    session: requests.Session | None = None, timeout: float = 20.0
) -> pd.DataFrame:
    client = session or requests.Session()
    response = client.get(
        UNIVERSE_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*;q=0.8"},
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_universe_csv(response.content)


def select_scan_universe(
    universe: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    as_of: datetime,
    config: ScanConfig | None = None,
) -> pd.DataFrame:
    config = config or ScanConfig()
    liquidity: dict[str, float] = {}
    for symbol, frame in histories.items():
        traded_value = (
            pd.to_numeric(frame["Close"], errors="coerce")
            * pd.to_numeric(frame["Volume"], errors="coerce")
        ).tail(config.liquidity_sessions)
        valid = traded_value.replace([np.inf, -np.inf], np.nan).dropna()
        if len(valid) >= config.liquidity_min_observations:
            liquidity[symbol] = float(valid.median())
    ranked = sorted(liquidity, key=lambda symbol: (-liquidity[symbol], symbol))
    ranks = {symbol: index + 1 for index, symbol in enumerate(ranked)}
    result = universe.copy()
    result["median_traded_value_60d"] = result["symbol"].map(liquidity)
    result["liquidity_rank"] = result["symbol"].map(ranks).astype("Int64")
    result["top_1000_liquid"] = (
        result["liquidity_rank"].le(config.liquidity_count).fillna(False).astype(bool)
    )
    as_of_date = pd.Timestamp(as_of)
    if as_of_date.tzinfo is not None:
        as_of_date = as_of_date.tz_localize(None)
    cutoff = as_of_date.normalize() - pd.Timedelta(days=config.recent_ipo_days)
    result["recent_ipo_overlay"] = pd.to_datetime(result["listing_date"]).ge(cutoff)
    selected = result[result["top_1000_liquid"] | result["recent_ipo_overlay"]]
    return selected.sort_values(
        ["top_1000_liquid", "liquidity_rank", "symbol"],
        ascending=[False, True, True],
        na_position="last",
        ignore_index=True,
    )
