"""Strict live breakout classification against completed-session pivots."""

from __future__ import annotations

import math

import pandas as pd

from nifty_vcp.models import BreakoutResult, QuoteRecord, QuoteStatus


def prior_pivot(frame: pd.DataFrame, sessions: int = 55) -> float:
    if len(frame) < sessions:
        raise ValueError(f"pivot requires at least {sessions} completed sessions")
    pivot = float(pd.to_numeric(frame["High"], errors="raise").tail(sessions).max())
    if not math.isfinite(pivot) or pivot <= 0:
        raise ValueError("pivot must be finite and positive")
    return pivot


def classify_breakout(
    symbol: str,
    frame: pd.DataFrame,
    quote: QuoteRecord,
    sessions: int = 55,
) -> BreakoutResult:
    pivot = prior_pivot(frame, sessions)
    if quote.price is None or quote.status == QuoteStatus.UNAVAILABLE:
        return BreakoutResult(
            symbol,
            None,
            pivot,
            None,
            False,
            quote.status,
            quote.timestamp,
            quote.reason or "quote unavailable",
        )
    price = float(quote.price)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("quote price must be finite and positive")
    breakout_pct = (price / pivot - 1.0) * 100.0
    if quote.status == QuoteStatus.LAST_AVAILABLE:
        reason = "market closed; latest observation only"
        is_breakout = False
    elif quote.status == QuoteStatus.DELAYED:
        reason = quote.reason or "delayed quote cannot confirm a live breakout"
        is_breakout = False
    else:
        is_breakout = price > pivot
        reason = "live price above pivot" if is_breakout else "live price not above pivot"
    return BreakoutResult(
        symbol,
        price,
        pivot,
        breakout_pct,
        is_breakout,
        quote.status,
        quote.timestamp,
        reason,
    )


def classify_high_rs_breakouts(
    setups: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    quotes: dict[str, QuoteRecord],
    sessions: int = 55,
) -> pd.DataFrame:
    rows = []
    for setup in setups.to_dict("records"):
        symbol = setup["symbol"]
        quote = quotes.get(
            symbol,
            QuoteRecord(
                symbol,
                None,
                None,
                QuoteStatus.UNAVAILABLE,
                None,
                "quote unavailable",
            ),
        )
        result = classify_breakout(symbol, histories[symbol], quote, sessions)
        row = dict(setup)
        row.update(
            {
                "live_price": result.live_price,
                "pivot_55": result.pivot,
                "breakout_pct": result.breakout_pct,
                "is_breakout": result.is_breakout,
                "quote_status": result.quote_status.value,
                "quote_timestamp": (
                    result.quote_timestamp.isoformat()
                    if result.quote_timestamp is not None
                    else ""
                ),
                "breakout_reason": result.reason,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)
