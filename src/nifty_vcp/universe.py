"""Official Nifty Total Market constituent loading."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import requests

UNIVERSE_URL = (
    "https://www.niftyindices.com/IndexConstituent/"
    "ind_niftytotalmarket_list.csv"
)
USER_AGENT = "Mozilla/5.0 (compatible; NiftyVCPResearch/0.1)"


def parse_universe_csv(content: bytes) -> pd.DataFrame:
    frame = pd.read_csv(BytesIO(content))
    frame.columns = [str(column).strip() for column in frame.columns]
    aliases = {column.lower(): column for column in frame.columns}
    symbol_column = aliases.get("symbol")
    company_column = aliases.get("company name") or aliases.get("company_name")
    if not symbol_column or not company_column:
        raise ValueError("universe must contain Company Name and Symbol columns")
    series_column = aliases.get("series")
    if series_column:
        frame = frame[frame[series_column].astype(str).str.strip().eq("EQ")]
    symbol = frame[symbol_column].astype(str).str.strip().str.upper()
    if symbol.duplicated().any():
        duplicates = sorted(symbol[symbol.duplicated(keep=False)].unique())
        raise ValueError(f"duplicate symbols: {', '.join(duplicates[:5])}")
    industry_column = aliases.get("industry")
    industry = (
        frame[industry_column].astype(str).str.strip()
        if industry_column
        else pd.Series("", index=frame.index)
    )
    result = pd.DataFrame(
        {
            "symbol": symbol,
            "company_name": frame[company_column].astype(str).str.strip(),
            "industry": industry,
            "yahoo_symbol": symbol + ".NS",
        }
    ).reset_index(drop=True)
    if not 650 <= len(result) <= 850:
        raise ValueError(
            f"official universe must contain between 650 and 850 stocks; got {len(result)}"
        )
    return result


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

