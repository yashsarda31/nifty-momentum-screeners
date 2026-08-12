from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from nifty_vcp.market_data import (
    collect_daily_histories,
    collect_latest_quotes,
    split_yahoo_download,
    validate_history,
)
from nifty_vcp.models import QuoteStatus, ScanConfig

TZ = ZoneInfo("Asia/Kolkata")


def price_frame(periods=280, end="2026-08-11"):
    index = pd.bdate_range(end=end, periods=periods)
    close = np.linspace(100.0, 150.0, periods)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(periods, 1_000_000.0),
        },
        index=index,
    )


@pytest.mark.parametrize(
    "bad, message",
    [
        (lambda f: f.drop(columns="Volume"), "missing columns"),
        (lambda f: f.assign(Close=0.0), "prices must be positive"),
        (lambda f: f.assign(Volume=-1), "volume must be nonnegative"),
        (lambda f: f.assign(High=f["Low"] - 1), "High must be at least Low"),
        (lambda f: f.iloc[:100], "at least 273"),
    ],
)
def test_validate_history_rejects_bad_frames(bad, message):
    with pytest.raises(ValueError, match=message):
        validate_history(bad(price_frame()))


def test_split_yahoo_download_supports_both_multiindex_orientations():
    one = price_frame()
    field_first = pd.concat({"AAA.NS": one, "BBB.NS": one * 2}, axis=1).swaplevel(
        axis=1
    )
    ticker_first = pd.concat({"AAA.NS": one, "BBB.NS": one * 2}, axis=1)
    first = split_yahoo_download(field_first, ["AAA.NS", "BBB.NS"])
    second = split_yahoo_download(ticker_first, ["AAA.NS", "BBB.NS"])
    pd.testing.assert_frame_equal(first["AAA.NS"], second["AAA.NS"])


def test_collect_daily_uses_design_options_and_excludes_stale_symbol():
    universe = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "yahoo_symbol": ["AAA.NS", "BBB.NS"],
        }
    )
    calls = []

    def downloader(tickers, **kwargs):
        calls.append((tickers, kwargs))
        frames = {
            "AAA.NS": price_frame(end="2026-08-11"),
            "BBB.NS": price_frame(end="2026-08-10"),
        }
        return pd.concat({ticker: frames[ticker] for ticker in tickers}, axis=1)

    histories, exclusions = collect_daily_histories(
        universe,
        downloader,
        datetime(2026, 8, 12, 10, 0, tzinfo=TZ),
        ScanConfig(daily_batch_size=2),
        sleep=lambda _seconds: None,
        jitter=lambda: 0.0,
    )
    assert list(histories) == ["AAA"]
    assert "stale latest bar" in exclusions["BBB"]
    assert calls[0][1] == {
        "period": "15mo",
        "interval": "1d",
        "auto_adjust": True,
        "repair": True,
        "progress": False,
        "threads": True,
        "timeout": 20.0,
    }


def test_failed_batch_is_split_to_isolate_one_bad_symbol():
    universe = pd.DataFrame(
        {
            "symbol": ["AAA", "BAD"],
            "yahoo_symbol": ["AAA.NS", "BAD.NS"],
        }
    )

    def downloader(tickers, **_kwargs):
        if "BAD.NS" in tickers:
            raise RuntimeError("provider failure")
        return price_frame()

    histories, exclusions = collect_daily_histories(
        universe,
        downloader,
        datetime(2026, 8, 12, 16, 0, tzinfo=TZ),
        ScanConfig(daily_batch_size=2, max_retries=1),
        sleep=lambda _seconds: None,
        jitter=lambda: 0.0,
    )
    assert list(histories) == ["AAA"]
    assert "provider failure" in exclusions["BAD"]


def test_quotes_classify_live_delayed_closed_and_unavailable():
    symbols = pd.DataFrame(
        {"symbol": ["AAA", "OLD", "MISS"], "yahoo_symbol": ["AAA.NS", "OLD.NS", "MISS.NS"]}
    )
    now = datetime(2026, 8, 12, 10, 0, tzinfo=TZ)
    index = pd.DatetimeIndex([now - timedelta(minutes=20), now])
    frames = {
        "AAA.NS": pd.DataFrame({"Close": [100.0, 101.0]}, index=index),
        "OLD.NS": pd.DataFrame({"Close": [99.0, np.nan]}, index=index),
    }

    def downloader(tickers, **kwargs):
        assert kwargs["period"] == "1d"
        assert kwargs["interval"] == "1m"
        assert kwargs["prepost"] is False
        available = {ticker: frames[ticker] for ticker in tickers if ticker in frames}
        return pd.concat(available, axis=1) if available else pd.DataFrame()

    quotes, exclusions = collect_latest_quotes(
        symbols,
        downloader,
        now,
        ScanConfig(quote_batch_size=3, max_retries=1),
        sleep=lambda _seconds: None,
        jitter=lambda: 0.0,
    )
    assert quotes["AAA"].status == QuoteStatus.LIVE
    assert quotes["OLD"].status == QuoteStatus.DELAYED
    assert quotes["MISS"].status == QuoteStatus.UNAVAILABLE
    assert "MISS" in exclusions

    closed, _ = collect_latest_quotes(
        symbols.iloc[:1],
        downloader,
        datetime(2026, 8, 12, 16, 0, tzinfo=TZ),
        ScanConfig(max_retries=1),
        sleep=lambda _seconds: None,
        jitter=lambda: 0.0,
    )
    assert closed["AAA"].status == QuoteStatus.LAST_AVAILABLE
