from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from nifty_vcp.breakouts import (
    classify_breakout,
    classify_high_rs_breakouts,
    prior_pivot,
)
from nifty_vcp.models import QuoteRecord, QuoteStatus

TZ = ZoneInfo("Asia/Kolkata")


def history():
    high = np.linspace(90.0, 100.0, 60)
    return pd.DataFrame(
        {"High": high, "Close": high - 1},
        index=pd.bdate_range("2026-01-01", periods=60),
    )


def quote(price, status=QuoteStatus.LIVE):
    return QuoteRecord(
        "AAA",
        price,
        datetime(2026, 8, 12, 10, 0, tzinfo=TZ),
        status,
        0.0,
        "",
    )


def test_prior_pivot_uses_latest_55_completed_highs():
    frame = history()
    frame.loc[frame.index[0], "High"] = 500.0
    assert prior_pivot(frame) == pytest.approx(100.0)


@pytest.mark.parametrize(
    "price, expected",
    [(99.0, False), (100.0, False), (100.01, True)],
)
def test_breakout_requires_strictly_above_pivot(price, expected):
    result = classify_breakout("AAA", history(), quote(price))
    assert result.is_breakout is expected
    assert result.breakout_pct == pytest.approx((price / 100.0 - 1) * 100)


@pytest.mark.parametrize(
    "status, reason",
    [
        (QuoteStatus.DELAYED, "delayed"),
        (QuoteStatus.LAST_AVAILABLE, "market closed"),
        (QuoteStatus.UNAVAILABLE, "unavailable"),
    ],
)
def test_non_live_quotes_cannot_create_breakout(status, reason):
    record = quote(110.0, status)
    if status == QuoteStatus.UNAVAILABLE:
        record = QuoteRecord("AAA", None, None, status, None, "quote unavailable")
    result = classify_breakout("AAA", history(), record)
    assert not result.is_breakout
    assert reason in result.reason.lower()


def test_classify_high_rs_breakouts_joins_setup_fields():
    setups = pd.DataFrame({"symbol": ["AAA"], "rs_rating": [99], "vcp_stars": [5]})
    result = classify_high_rs_breakouts(
        setups, {"AAA": history()}, {"AAA": quote(101.0)}
    )
    assert bool(result.iloc[0]["is_breakout"])
    assert result.iloc[0]["rs_rating"] == 99
