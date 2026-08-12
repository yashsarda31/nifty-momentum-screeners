"""End-to-end scan orchestration and coverage gates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from nifty_vcp.breakouts import classify_high_rs_breakouts
from nifty_vcp.market_data import collect_daily_histories, collect_latest_quotes
from nifty_vcp.models import QuoteStatus, RunStatus, ScanConfig, ScanSummary
from nifty_vcp.momentum import rank_relative_strength
from nifty_vcp.sessions import INDIA_TZ, market_state
from nifty_vcp.storage import publish_run
from nifty_vcp.universe import UNIVERSE_URL, fetch_universe
from nifty_vcp.vcp import score_high_rs

YAHOO_SOURCE = "https://finance.yahoo.com/"


@dataclass(frozen=True)
class PipelineDependencies:
    universe_loader: Callable
    daily_loader: Callable
    quote_loader: Callable
    ranker: Callable
    scorer: Callable
    classifier: Callable
    publisher: Callable


def default_dependencies() -> PipelineDependencies:
    return PipelineDependencies(
        universe_loader=lambda timeout: fetch_universe(timeout=timeout),
        daily_loader=lambda universe, now, config: collect_daily_histories(
            universe, now=now, config=config
        ),
        quote_loader=lambda symbols, now, config: collect_latest_quotes(
            symbols, now=now, config=config
        ),
        ranker=rank_relative_strength,
        scorer=score_high_rs,
        classifier=classify_high_rs_breakouts,
        publisher=publish_run,
    )


def _empty_artifacts() -> dict[str, pd.DataFrame]:
    return {
        "all_rankings.csv": pd.DataFrame(columns=["symbol", "rs_rating"]),
        "high_rs_setups.csv": pd.DataFrame(columns=["symbol", "vcp_stars"]),
        "live_breakouts.csv": pd.DataFrame(columns=["symbol", "live_price"]),
        "exclusions.csv": pd.DataFrame(columns=["symbol", "stage", "reason"]),
        "chart_history.csv.gz": pd.DataFrame(columns=["symbol", "date"]),
    }


def _chart_history(
    histories: dict[str, pd.DataFrame], symbols: list[str]
) -> pd.DataFrame:
    frames = []
    for symbol in symbols:
        frame = histories[symbol].copy().reset_index(names="date")
        frame.insert(0, "symbol", symbol)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(
            columns=["symbol", "date", "Open", "High", "Low", "Close", "Volume"]
        )
    return pd.concat(frames, ignore_index=True)


def _exclusion_frame(
    history_exclusions: dict[str, str], quote_exclusions: dict[str, str]
) -> pd.DataFrame:
    rows = [
        {"symbol": symbol, "stage": "history", "reason": reason}
        for symbol, reason in history_exclusions.items()
    ]
    rows.extend(
        {"symbol": symbol, "stage": "quote", "reason": reason}
        for symbol, reason in quote_exclusions.items()
    )
    return pd.DataFrame(rows, columns=["symbol", "stage", "reason"])


def run_scan(
    config: ScanConfig | None = None,
    dependencies: PipelineDependencies | None = None,
    now: datetime | None = None,
    output_root: str | Path = "outputs",
) -> ScanSummary:
    config = config or ScanConfig()
    dependencies = dependencies or default_dependencies()
    started = now or datetime.now(tz=INDIA_TZ)
    if started.tzinfo is None:
        started = started.replace(tzinfo=INDIA_TZ)
    try:
        universe = dependencies.universe_loader(config.request_timeout)
    except Exception as exc:  # noqa: BLE001 - publish provider diagnostic
        finished = datetime.now(tz=INDIA_TZ)
        manifest = {
            "schema_version": 1,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "status": RunStatus.INCOMPLETE.value,
            "outcome": RunStatus.INCOMPLETE.value,
            "universe_source": UNIVERSE_URL,
            "price_source": YAHOO_SOURCE,
            "universe_count": 0,
            "valid_history_count": 0,
            "historical_coverage": 0.0,
            "high_rs_count": 0,
            "valid_quote_count": 0,
            "quote_coverage": 0.0,
            "breakout_count": 0,
            "fatal_error": str(exc),
        }
        output_path = dependencies.publisher(output_root, _empty_artifacts(), manifest)
        return ScanSummary(
            RunStatus.INCOMPLETE,
            RunStatus.INCOMPLETE.value,
            0,
            0,
            0,
            0,
            0,
            started,
            finished,
            output_path,
        )
    if config.max_symbols is not None:
        universe = universe.head(config.max_symbols).copy()
    universe_count = len(universe)
    histories, history_exclusions = dependencies.daily_loader(
        universe, started, config
    )
    valid_universe = universe[universe["symbol"].isin(histories)].copy()
    rankings = dependencies.ranker(histories, valid_universe, config)
    setups = dependencies.scorer(histories, rankings, config)
    high_rs_symbols = list(setups["symbol"]) if "symbol" in setups else []
    quote_universe = universe[universe["symbol"].isin(high_rs_symbols)].copy()
    quotes, quote_exclusions = dependencies.quote_loader(
        quote_universe, started, config
    )
    classified = dependencies.classifier(
        setups, histories, quotes, config.pivot_sessions
    )
    if "is_breakout" in classified:
        breakouts = classified[classified["is_breakout"]].copy()
    else:
        breakouts = pd.DataFrame(columns=[*classified.columns, "is_breakout"])
    valid_history_count = len(histories)
    historical_coverage = (
        valid_history_count / universe_count if universe_count else 0.0
    )
    high_rs_count = len(high_rs_symbols)
    valid_quote_count = sum(
        quote.price is not None and quote.status != QuoteStatus.UNAVAILABLE
        for quote in quotes.values()
    )
    quote_coverage = valid_quote_count / high_rs_count if high_rs_count else 1.0
    complete = (
        historical_coverage >= config.coverage_threshold
        and quote_coverage >= config.coverage_threshold
    )
    status = RunStatus.COMPLETE if complete else RunStatus.INCOMPLETE
    breakout_count = len(breakouts)
    outcome = (
        RunStatus.INCOMPLETE.value
        if not complete
        else ("BREAKOUTS FOUND" if breakout_count else "NO BREAKOUTS")
    )
    finished = datetime.now(tz=INDIA_TZ)
    exclusions = _exclusion_frame(history_exclusions, quote_exclusions)
    reason_counts = Counter(exclusions["reason"]) if not exclusions.empty else Counter()
    manifest = {
        "schema_version": 1,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "market_state": market_state(started).value,
        "status": status.value,
        "outcome": outcome,
        "universe_source": UNIVERSE_URL,
        "price_source": YAHOO_SOURCE,
        "universe_count": universe_count,
        "valid_history_count": valid_history_count,
        "excluded_history_count": len(history_exclusions),
        "historical_coverage": round(historical_coverage, 6),
        "high_rs_count": high_rs_count,
        "valid_quote_count": valid_quote_count,
        "quote_coverage": round(quote_coverage, 6),
        "breakout_count": breakout_count,
        "thresholds": {
            "high_rs": config.high_rs_threshold,
            "pivot_sessions": config.pivot_sessions,
            "coverage": config.coverage_threshold,
            "momentum_sessions": list(config.momentum_sessions),
            "momentum_weights": list(config.momentum_weights),
        },
        "exclusion_reason_counts": dict(reason_counts),
    }
    artifacts = {
        "all_rankings.csv": rankings,
        "high_rs_setups.csv": classified,
        "live_breakouts.csv": breakouts,
        "exclusions.csv": exclusions,
        "chart_history.csv.gz": _chart_history(histories, high_rs_symbols),
    }
    output_path = dependencies.publisher(output_root, artifacts, manifest)
    return ScanSummary(
        status,
        outcome,
        universe_count,
        valid_history_count,
        high_rs_count,
        valid_quote_count,
        breakout_count,
        started,
        finished,
        output_path,
    )
