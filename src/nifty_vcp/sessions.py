"""NSE market-session time handling."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from nifty_vcp.models import MarketState


INDIA_TZ = ZoneInfo("Asia/Kolkata")


def _india_now(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=INDIA_TZ)
    return now.astimezone(INDIA_TZ)


def market_state(now: datetime) -> MarketState:
    current = _india_now(now)
    if current.weekday() >= 5:
        return MarketState.CLOSED
    if current.time() < time(9, 15):
        return MarketState.PREOPEN
    if current.time() < time(15, 30):
        return MarketState.OPEN
    return MarketState.CLOSED


def drop_unfinished_daily_bar(frame: pd.DataFrame, now: datetime) -> pd.DataFrame:
    result = frame.copy()
    index = pd.DatetimeIndex(pd.to_datetime(result.index))
    if index.tz is not None:
        index = index.tz_convert(INDIA_TZ).tz_localize(None)
    result.index = index.normalize()
    result = result.sort_index()
    if result.index.has_duplicates:
        raise ValueError("dates must be unique")
    current = _india_now(now)
    if market_state(current) in {MarketState.OPEN, MarketState.PREOPEN}:
        result = result[result.index.date < current.date()]
    return result
