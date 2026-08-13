from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from nifty_vcp.models import ScanConfig
from nifty_vcp.universe import (
    fetch_universe,
    parse_universe_csv,
    select_scan_universe,
)

TZ = ZoneInfo("Asia/Kolkata")


def equity_csv() -> bytes:
    return (
        b"SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,ISIN NUMBER\n"
        b"OLD,Old Limited,EQ,01-JAN-2000,INE000A01001\n"
        b"IPO,New Limited,EQ,01-AUG-2026,INE000A01002\n"
        b"BESEC,Be Limited,BE,01-JAN-2020,INE000A01003\n"
    )


def price_frame(periods: int, close: float, volume: float) -> pd.DataFrame:
    index = pd.bdate_range(end="2026-08-12", periods=periods)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": volume,
        },
        index=index,
    )


def test_parse_universe_keeps_eq_metadata():
    frame = parse_universe_csv(equity_csv())
    assert list(frame.columns) == [
        "symbol",
        "company_name",
        "industry",
        "series",
        "isin",
        "listing_date",
        "yahoo_symbol",
    ]
    assert list(frame["symbol"]) == ["OLD", "IPO"]
    assert frame.loc[1, "listing_date"] == pd.Timestamp("2026-08-01")
    assert frame.loc[1, "isin"] == "INE000A01002"
    assert frame.loc[1, "yahoo_symbol"] == "IPO.NS"


def test_parse_universe_rejects_duplicates_and_bad_dates():
    duplicate = equity_csv() + b"OLD,Duplicate,EQ,01-JAN-2001,INE000A01004\n"
    with pytest.raises(ValueError, match="duplicate symbols"):
        parse_universe_csv(duplicate)
    invalid = equity_csv().replace(b"01-AUG-2026", b"not-a-date")
    with pytest.raises(ValueError, match="listing dates"):
        parse_universe_csv(invalid)


def test_selection_adds_recent_ipo_outside_liquidity_cutoff():
    universe = pd.DataFrame(
        {
            "symbol": ["A", "B", "IPO"],
            "company_name": ["A", "B", "IPO"],
            "industry": ["", "", ""],
            "series": ["EQ", "EQ", "EQ"],
            "isin": ["1", "2", "3"],
            "listing_date": pd.to_datetime(
                ["2000-01-01", "2001-01-01", "2026-08-01"]
            ),
            "yahoo_symbol": ["A.NS", "B.NS", "IPO.NS"],
        }
    )
    histories = {
        "A": price_frame(60, close=100, volume=10_000),
        "B": price_frame(60, close=100, volume=9_000),
        "IPO": price_frame(15, close=100, volume=1_000),
    }
    selected = select_scan_universe(
        universe,
        histories,
        datetime(2026, 8, 13, tzinfo=TZ),
        ScanConfig(liquidity_count=1),
    ).set_index("symbol")
    assert set(selected.index) == {"A", "IPO"}
    assert bool(selected.loc["A", "top_1000_liquid"])
    assert bool(selected.loc["IPO", "recent_ipo_overlay"])
    assert not bool(selected.loc["IPO", "top_1000_liquid"])
    assert pd.isna(selected.loc["IPO", "liquidity_rank"])


def test_liquidity_requires_forty_valid_observations_and_ties_sort_by_symbol():
    universe = pd.DataFrame(
        {
            "symbol": ["B", "A", "THIN"],
            "company_name": ["B", "A", "Thin"],
            "industry": ["", "", ""],
            "series": ["EQ"] * 3,
            "isin": ["1", "2", "3"],
            "listing_date": pd.to_datetime(["2000-01-01"] * 3),
            "yahoo_symbol": ["B.NS", "A.NS", "THIN.NS"],
        }
    )
    thin = price_frame(40, 100, 1_000)
    thin.iloc[0, thin.columns.get_loc("Volume")] = np.nan
    histories = {
        "A": price_frame(60, 100, 10_000),
        "B": price_frame(60, 100, 10_000),
        "THIN": thin,
    }
    selected = select_scan_universe(
        universe,
        histories,
        datetime(2026, 8, 13, tzinfo=TZ),
        ScanConfig(liquidity_count=2),
    ).set_index("symbol")
    assert selected.loc["A", "liquidity_rank"] == 1
    assert selected.loc["B", "liquidity_rank"] == 2
    assert "THIN" not in selected.index


def test_fetch_universe_sets_headers_timeout_and_checks_status():
    class Response:
        content = equity_csv()

        def __init__(self):
            self.checked = False

        def raise_for_status(self):
            self.checked = True

    class Session:
        def __init__(self):
            self.response = Response()
            self.kwargs = None

        def get(self, _url, **kwargs):
            self.kwargs = kwargs
            return self.response

    session = Session()
    result = fetch_universe(session=session, timeout=12.5)
    assert isinstance(result, pd.DataFrame)
    assert session.response.checked
    assert session.kwargs["timeout"] == 12.5
    assert "Mozilla" in session.kwargs["headers"]["User-Agent"]
