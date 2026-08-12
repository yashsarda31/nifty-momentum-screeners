from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from nifty_vcp.models import MarketState
from nifty_vcp.sessions import drop_unfinished_daily_bar, market_state

TZ = ZoneInfo("Asia/Kolkata")


def test_market_state_distinguishes_preopen_open_and_closed():
    assert market_state(datetime(2026, 8, 12, 9, 0, tzinfo=TZ)) == MarketState.PREOPEN
    assert market_state(datetime(2026, 8, 12, 10, 0, tzinfo=TZ)) == MarketState.OPEN
    assert market_state(datetime(2026, 8, 12, 15, 29, tzinfo=TZ)) == MarketState.OPEN
    assert market_state(datetime(2026, 8, 12, 16, 0, tzinfo=TZ)) == MarketState.CLOSED
    assert market_state(datetime(2026, 8, 9, 10, 0, tzinfo=TZ)) == MarketState.CLOSED


def test_drop_unfinished_bar_before_close_and_keep_after_close():
    original = pd.DataFrame(
        {"Close": [100.0, 101.0]},
        index=pd.to_datetime(["2026-08-11", "2026-08-12"]),
    )
    before = drop_unfinished_daily_bar(
        original, datetime(2026, 8, 12, 14, 0, tzinfo=TZ)
    )
    after = drop_unfinished_daily_bar(
        original, datetime(2026, 8, 12, 16, 0, tzinfo=TZ)
    )
    assert list(before.index.date) == [date(2026, 8, 11)]
    assert len(after) == 2
    assert len(original) == 2


def test_drop_unfinished_bar_normalizes_aware_index():
    index = pd.DatetimeIndex(["2026-08-11 00:00:00+00:00"])
    frame = pd.DataFrame({"Close": [100.0]}, index=index)
    result = drop_unfinished_daily_bar(
        frame, datetime(2026, 8, 12, 10, 0, tzinfo=TZ)
    )
    assert result.index.tz is None
