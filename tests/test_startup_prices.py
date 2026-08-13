from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from nifty_vcp.models import QuoteRecord, QuoteStatus
from nifty_vcp.startup_prices import attach_startup_prices, fetch_startup_prices

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 8, 14, 10, 0, tzinfo=TZ)


def test_startup_snapshot_retains_unavailable_symbols():
    universe = pd.DataFrame(
        {
            "symbol": ["AAA", "MISS"],
            "yahoo_symbol": ["AAA.NS", "MISS.NS"],
        }
    )
    records = {
        "AAA": QuoteRecord("AAA", 105.0, NOW, QuoteStatus.LIVE, 0.0, ""),
        "MISS": QuoteRecord(
            "MISS", None, None, QuoteStatus.UNAVAILABLE, None, "provider failure"
        ),
    }

    snapshot = fetch_startup_prices(
        universe,
        now=NOW,
        quote_loader=lambda symbols, now, config: (
            records,
            {"MISS": "provider failure"},
        ),
    )

    assert snapshot.fetched_at == NOW
    assert snapshot.table["symbol"].tolist() == ["AAA", "MISS"]
    assert snapshot.table.loc[0, "latest_price"] == 105.0
    assert snapshot.table.loc[0, "quote_timestamp"] == NOW.isoformat()
    assert snapshot.table.loc[1, "quote_status"] == "UNAVAILABLE"
    assert snapshot.table.loc[1, "quote_reason"] == "provider failure"


def test_startup_snapshot_passes_timestamp_and_config_by_keyword():
    universe = pd.DataFrame(
        {"symbol": ["AAA"], "yahoo_symbol": ["AAA.NS"]}
    )
    received = {}

    def loader(symbols, downloader=None, now=None, config=None):
        received.update(
            {"symbols": symbols, "downloader": downloader, "now": now, "config": config}
        )
        return {}, {"AAA": "quote unavailable"}

    fetch_startup_prices(universe, now=NOW, quote_loader=loader)

    assert received["symbols"] is universe
    assert received["downloader"] is None
    assert received["now"] == NOW
    assert received["config"] is not None


def test_attach_startup_prices_preserves_daily_close_and_calculates_change():
    frame = pd.DataFrame(
        {"symbol": ["AAA", "MISS"], "latest_close": [100.0, 90.0]}
    )
    quote_table = pd.DataFrame(
        {
            "symbol": ["AAA", "MISS"],
            "latest_price": [105.0, None],
            "quote_timestamp": [NOW.isoformat(), ""],
            "quote_status": ["LIVE", "UNAVAILABLE"],
            "quote_age_minutes": [0.0, None],
            "quote_reason": ["", "provider failure"],
        }
    )

    result = attach_startup_prices(frame, quote_table, "latest_close")

    assert result["latest_close"].tolist() == [100.0, 90.0]
    assert result.loc[0, "price_change_pct"] == pytest.approx(5.0)
    assert pd.isna(result.loc[1, "price_change_pct"])


def test_attach_startup_prices_replaces_older_display_columns():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "latest_close": [100.0],
            "latest_price": [99.0],
            "quote_status": ["DELAYED"],
        }
    )
    quote_table = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "latest_price": [101.0],
            "quote_timestamp": [NOW.isoformat()],
            "quote_status": ["LIVE"],
            "quote_age_minutes": [0.0],
            "quote_reason": [""],
        }
    )

    result = attach_startup_prices(frame, quote_table, "latest_close")

    assert result.loc[0, "latest_price"] == 101.0
    assert result.loc[0, "quote_status"] == "LIVE"
