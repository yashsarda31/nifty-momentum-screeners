"""Yahoo Finance data loading with bounded failure isolation."""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Iterable
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

from nifty_vcp.models import (
    MarketState,
    QuoteRecord,
    QuoteStatus,
    ScanConfig,
)
from nifty_vcp.sessions import INDIA_TZ, drop_unfinished_daily_bar, market_state

REQUIRED_OHLCV = ("Open", "High", "Low", "Close", "Volume")


def validate_history(frame: pd.DataFrame, minimum_sessions: int = 273) -> None:
    missing = [column for column in REQUIRED_OHLCV if column not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")
    if len(frame) < minimum_sessions:
        raise ValueError(f"history must contain at least {minimum_sessions} sessions")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("index must be a DatetimeIndex")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("dates must be unique and increasing")
    numeric = frame.loc[:, REQUIRED_OHLCV].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("OHLCV values must be finite")
    if (numeric[["Open", "High", "Low", "Close"]] <= 0).any().any():
        raise ValueError("prices must be positive")
    if (numeric["Volume"] < 0).any():
        raise ValueError("volume must be nonnegative")
    if (numeric["High"] < numeric["Low"]).any():
        raise ValueError("High must be at least Low")
    if (numeric["High"] < numeric[["Open", "Close"]].max(axis=1)).any():
        raise ValueError("High must cover Open and Close")
    if (numeric["Low"] > numeric[["Open", "Close"]].min(axis=1)).any():
        raise ValueError("Low must cover Open and Close")


def split_yahoo_download(
    raw: pd.DataFrame | None, tickers: Iterable[str]
) -> dict[str, pd.DataFrame]:
    requested = list(tickers)
    if raw is None or raw.empty:
        return {}
    if not isinstance(raw.columns, pd.MultiIndex):
        return {requested[0]: raw.copy()} if len(requested) == 1 else {}
    output: dict[str, pd.DataFrame] = {}
    for ticker in requested:
        if ticker in raw.columns.get_level_values(0):
            frame = raw.xs(ticker, axis=1, level=0, drop_level=True)
        elif ticker in raw.columns.get_level_values(1):
            frame = raw.xs(ticker, axis=1, level=1, drop_level=True)
        else:
            continue
        frame.columns = [str(column) for column in frame.columns]
        output[ticker] = frame.dropna(how="all")
    return output


def yahoo_download(tickers: list[str], **kwargs) -> pd.DataFrame:
    return yf.download(tickers=tickers, **kwargs)


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _download_with_isolation(
    tickers: list[str],
    downloader: Callable[..., pd.DataFrame],
    kwargs: dict,
    config: ScanConfig,
    sleep: Callable[[float], None],
    jitter: Callable[[], float],
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    last_error = "empty provider response"
    for attempt in range(config.max_retries):
        try:
            frames = split_yahoo_download(downloader(tickers, **kwargs), tickers)
            if frames:
                missing = [ticker for ticker in tickers if ticker not in frames]
                if not missing:
                    return frames, {}
                if len(tickers) == 1:
                    return {}, {tickers[0]: "empty provider response"}
                found = dict(frames)
                retry_frames, errors = _download_with_isolation(
                    missing, downloader, kwargs, config, sleep, jitter
                )
                found.update(retry_frames)
                return found, errors
        except Exception as exc:  # noqa: BLE001 - isolate arbitrary provider failures
            last_error = str(exc) or type(exc).__name__
        if attempt + 1 < config.max_retries:
            sleep((2**attempt) + max(0.0, jitter()))
    if len(tickers) == 1:
        return {}, {tickers[0]: last_error}
    midpoint = math.ceil(len(tickers) / 2)
    left, left_errors = _download_with_isolation(
        tickers[:midpoint], downloader, kwargs, config, sleep, jitter
    )
    right, right_errors = _download_with_isolation(
        tickers[midpoint:], downloader, kwargs, config, sleep, jitter
    )
    left.update(right)
    left_errors.update(right_errors)
    return left, left_errors


def collect_daily_histories(
    universe: pd.DataFrame,
    downloader: Callable[..., pd.DataFrame] = yahoo_download,
    now: datetime | None = None,
    config: ScanConfig | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    config = config or ScanConfig()
    now = now or datetime.now(tz=INDIA_TZ)
    yahoo_to_symbol = dict(zip(universe["yahoo_symbol"], universe["symbol"], strict=True))
    raw_frames: dict[str, pd.DataFrame] = {}
    exclusions: dict[str, str] = {}
    kwargs = {
        "period": "15mo",
        "interval": "1d",
        "auto_adjust": True,
        "repair": True,
        "progress": False,
        "threads": True,
        "timeout": config.request_timeout,
    }
    for batch in _chunks(list(yahoo_to_symbol), config.daily_batch_size):
        frames, errors = _download_with_isolation(
            batch, downloader, kwargs, config, sleep, jitter
        )
        raw_frames.update(frames)
        exclusions.update(
            {yahoo_to_symbol[ticker]: reason for ticker, reason in errors.items()}
        )
    accepted: dict[str, pd.DataFrame] = {}
    for yahoo_symbol, frame in raw_frames.items():
        symbol = yahoo_to_symbol[yahoo_symbol]
        try:
            completed = drop_unfinished_daily_bar(frame, now)
            validate_history(completed)
            accepted[symbol] = completed.loc[:, REQUIRED_OHLCV].astype(float)
        except ValueError as exc:
            exclusions[symbol] = str(exc)
    if not accepted:
        return {}, exclusions
    latest_dates = pd.Series({symbol: frame.index[-1] for symbol, frame in accepted.items()})
    counts = latest_dates.value_counts()
    max_count = counts.max()
    reference = max(counts[counts == max_count].index)
    for symbol, latest in latest_dates.items():
        if latest < reference:
            exclusions[symbol] = (
                f"stale latest bar: expected {reference.date()}, got {latest.date()}"
            )
            accepted.pop(symbol)
    return dict(sorted(accepted.items())), exclusions


def _quote_timestamp(timestamp, now: datetime) -> datetime:
    parsed = pd.Timestamp(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(INDIA_TZ)
    else:
        parsed = parsed.tz_convert(INDIA_TZ)
    return parsed.to_pydatetime()


def collect_latest_quotes(
    symbols: pd.DataFrame,
    downloader: Callable[..., pd.DataFrame] = yahoo_download,
    now: datetime | None = None,
    config: ScanConfig | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> tuple[dict[str, QuoteRecord], dict[str, str]]:
    config = config or ScanConfig()
    now = now or datetime.now(tz=INDIA_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=INDIA_TZ)
    else:
        now = now.astimezone(INDIA_TZ)
    yahoo_to_symbol = dict(zip(symbols["yahoo_symbol"], symbols["symbol"], strict=True))
    kwargs = {
        "period": "1d",
        "interval": "1m",
        "auto_adjust": True,
        "repair": True,
        "prepost": False,
        "progress": False,
        "threads": True,
        "timeout": config.request_timeout,
    }
    raw_frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for batch in _chunks(list(yahoo_to_symbol), config.quote_batch_size):
        frames, batch_errors = _download_with_isolation(
            batch, downloader, kwargs, config, sleep, jitter
        )
        raw_frames.update(frames)
        errors.update(batch_errors)
    quotes: dict[str, QuoteRecord] = {}
    exclusions: dict[str, str] = {}
    state = market_state(now)
    for yahoo_symbol, symbol in yahoo_to_symbol.items():
        frame = raw_frames.get(yahoo_symbol)
        if frame is None or "Close" not in frame:
            reason = errors.get(yahoo_symbol, "quote unavailable")
            quotes[symbol] = QuoteRecord(
                symbol, None, None, QuoteStatus.UNAVAILABLE, None, reason
            )
            exclusions[symbol] = reason
            continue
        close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
        if close.empty:
            reason = "quote has no finite close"
            quotes[symbol] = QuoteRecord(
                symbol, None, None, QuoteStatus.UNAVAILABLE, None, reason
            )
            exclusions[symbol] = reason
            continue
        timestamp = _quote_timestamp(close.index[-1], now)
        age = max(0.0, (now - timestamp).total_seconds() / 60.0)
        if state != MarketState.OPEN:
            status = QuoteStatus.LAST_AVAILABLE
            reason = "market closed; latest observation only"
        elif age > 15.0:
            status = QuoteStatus.DELAYED
            reason = f"quote is {age:.1f} minutes old"
        else:
            status = QuoteStatus.LIVE
            reason = ""
        quotes[symbol] = QuoteRecord(
            symbol, float(close.iloc[-1]), timestamp, status, age, reason
        )
    return quotes, exclusions
