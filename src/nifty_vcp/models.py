"""Typed records shared across the scanner."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType


class RunStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "SCAN INCOMPLETE"


class MarketState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PREOPEN = "PREOPEN"


class QuoteStatus(StrEnum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    LAST_AVAILABLE = "LAST AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ScreenerState(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO MATCH"
    NOT_ELIGIBLE = "NOT ELIGIBLE"
    INCOMPLETE = "SCAN INCOMPLETE"


@dataclass(frozen=True)
class ScanConfig:
    high_rs_threshold: int = 80
    pivot_sessions: int = 55
    coverage_threshold: float = 0.90
    momentum_sessions: tuple[int, ...] = (63, 126, 189, 252)
    momentum_weights: tuple[float, ...] = (0.40, 0.20, 0.20, 0.20)
    daily_batch_size: int = 75
    quote_batch_size: int = 40
    request_timeout: float = 20.0
    max_retries: int = 3
    max_symbols: int | None = None
    liquidity_count: int = 1_000
    liquidity_sessions: int = 60
    liquidity_min_observations: int = 40
    recent_ipo_days: int = 730
    minimum_history_sessions: int = 15

    def __post_init__(self) -> None:
        if not 0 < self.coverage_threshold <= 1:
            raise ValueError("coverage_threshold must be in (0, 1]")
        if not 1 <= self.high_rs_threshold <= 99:
            raise ValueError("high_rs_threshold must be in [1, 99]")
        if self.pivot_sessions < 2:
            raise ValueError("pivot_sessions must be at least 2")
        if len(self.momentum_sessions) != len(self.momentum_weights):
            raise ValueError("momentum sessions and weights must align")
        if not math.isclose(sum(self.momentum_weights), 1.0):
            raise ValueError("momentum weights must sum to 1")
        if self.liquidity_count < 1:
            raise ValueError("liquidity_count must be positive")
        if self.liquidity_sessions < 1:
            raise ValueError("liquidity_sessions must be positive")
        if not 1 <= self.liquidity_min_observations <= self.liquidity_sessions:
            raise ValueError(
                "liquidity_min_observations must be between 1 and liquidity_sessions"
            )
        if self.recent_ipo_days < 1:
            raise ValueError("recent_ipo_days must be positive")
        if self.minimum_history_sessions < 15:
            raise ValueError("minimum_history_sessions must be at least 15")


@dataclass(frozen=True)
class QuoteRecord:
    symbol: str
    price: float | None
    timestamp: datetime | None
    status: QuoteStatus
    age_minutes: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class VCPResult:
    total_stars: int
    components: Mapping[str, bool]
    evidence: Mapping[str, float | bool | str]

    def __post_init__(self) -> None:
        if not 0 <= self.total_stars <= 5:
            raise ValueError("total_stars must be in [0, 5]")
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


@dataclass(frozen=True)
class BreakoutResult:
    symbol: str
    live_price: float | None
    pivot: float
    breakout_pct: float | None
    is_breakout: bool
    quote_status: QuoteStatus
    quote_timestamp: datetime | None
    reason: str = ""


@dataclass(frozen=True)
class ScanSummary:
    status: RunStatus
    outcome: str
    universe_count: int
    valid_history_count: int
    high_rs_count: int
    valid_quote_count: int
    breakout_count: int
    started_at: datetime
    finished_at: datetime
    output_path: Path

    def __post_init__(self) -> None:
        counts = (
            self.universe_count,
            self.valid_history_count,
            self.high_rs_count,
            self.valid_quote_count,
            self.breakout_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("scan counts must be nonnegative")
