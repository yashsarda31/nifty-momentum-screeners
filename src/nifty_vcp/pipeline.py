"""End-to-end scan orchestration and coverage gates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from nifty_vcp.breakouts import classify_high_rs_breakouts
from nifty_vcp.earnings import fetch_earnings_events
from nifty_vcp.features import build_feature_matrix, history_evidence
from nifty_vcp.market_data import (
    collect_benchmark_history,
    collect_daily_histories,
    collect_latest_quotes,
)
from nifty_vcp.models import QuoteStatus, RunStatus, ScanConfig, ScanSummary
from nifty_vcp.momentum import rank_relative_strength
from nifty_vcp.screeners import evaluate_all_screeners
from nifty_vcp.sessions import INDIA_TZ, market_state
from nifty_vcp.storage import publish_run
from nifty_vcp.universe import UNIVERSE_URL, fetch_universe, select_scan_universe
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
    benchmark_loader: Callable
    universe_selector: Callable
    feature_builder: Callable
    earnings_loader: Callable
    screener_runner: Callable
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
        benchmark_loader=collect_benchmark_history,
        universe_selector=select_scan_universe,
        feature_builder=build_feature_matrix,
        earnings_loader=lambda symbols, now, timeout: fetch_earnings_events(
            symbols, pd.Timestamp(now), timeout
        ),
        screener_runner=evaluate_all_screeners,
        publisher=publish_run,
    )


def _empty_artifacts() -> dict[str, pd.DataFrame]:
    return {
        "all_rankings.csv": pd.DataFrame(columns=["symbol", "rs_rating"]),
        "high_rs_setups.csv": pd.DataFrame(columns=["symbol", "vcp_stars"]),
        "live_breakouts.csv": pd.DataFrame(columns=["symbol", "live_price"]),
        "exclusions.csv": pd.DataFrame(columns=["symbol", "stage", "reason"]),
        "chart_history.csv.gz": pd.DataFrame(columns=["symbol", "date"]),
        "selected_universe.csv": pd.DataFrame(columns=["symbol", "liquidity_rank"]),
        "screener_features.csv": pd.DataFrame(columns=["symbol", "price_date"]),
        "screener_matches.csv": pd.DataFrame(columns=["symbol", "screener"]),
        "earnings_events.csv": pd.DataFrame(columns=["symbol", "event_type"]),
    }


def _chart_history(
    histories: dict[str, pd.DataFrame], symbols: list[str]
) -> pd.DataFrame:
    selected = {symbol: histories[symbol] for symbol in symbols if symbol in histories}
    evidence = history_evidence(selected)
    if "week_ending" in evidence:
        evidence = evidence.drop(columns="week_ending")
    return evidence


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


def _fatal_manifest(started: datetime, finished: datetime, exc: Exception) -> dict:
    return {
        "schema_version": 2,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "status": RunStatus.INCOMPLETE.value,
        "outcome": RunStatus.INCOMPLETE.value,
        "universe_source": UNIVERSE_URL,
        "price_source": YAHOO_SOURCE,
        "source_universe_count": 0,
        "universe_count": 0,
        "selected_universe_count": 0,
        "valid_history_count": 0,
        "historical_coverage": 0.0,
        "high_rs_count": 0,
        "valid_quote_count": 0,
        "quote_coverage": 0.0,
        "breakout_count": 0,
        "fatal_error": str(exc),
    }


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
        manifest = _fatal_manifest(started, finished, exc)
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
    source_universe_count = len(universe)
    histories, history_exclusions = dependencies.daily_loader(universe, started, config)
    selected_universe = dependencies.universe_selector(
        universe, histories, started, config
    )
    selected_symbols = list(selected_universe["symbol"])
    selected_histories = {
        symbol: histories[symbol] for symbol in selected_symbols if symbol in histories
    }

    momentum_sessions = max(config.momentum_sessions) + 1
    momentum_histories = {
        symbol: frame
        for symbol, frame in selected_histories.items()
        if len(frame) >= momentum_sessions
    }
    momentum_universe = selected_universe[
        selected_universe["symbol"].isin(momentum_histories)
    ]
    rankings = dependencies.ranker(momentum_histories, momentum_universe, config)
    vcp_histories = {
        symbol: frame for symbol, frame in momentum_histories.items() if len(frame) >= 273
    }
    vcp_rankings = rankings[rankings["symbol"].isin(vcp_histories)].copy()
    setups = dependencies.scorer(vcp_histories, vcp_rankings, config)

    high_rs_symbols = list(setups["symbol"]) if "symbol" in setups else []
    quote_universe = selected_universe[
        selected_universe["symbol"].isin(high_rs_symbols)
    ].copy()
    quotes, quote_exclusions = dependencies.quote_loader(quote_universe, started, config)
    classified = dependencies.classifier(
        setups, selected_histories, quotes, config.pivot_sessions
    )
    if "is_breakout" in classified:
        breakouts = classified[classified["is_breakout"]].copy()
    else:
        breakouts = pd.DataFrame(columns=[*classified.columns, "is_breakout"])

    benchmark_status = "COMPLETE"
    try:
        benchmark = dependencies.benchmark_loader(started, config)
    except Exception:  # noqa: BLE001 - affects only benchmark-dependent screener
        benchmark = pd.DataFrame(columns=["Close"])
        benchmark_status = RunStatus.INCOMPLETE.value
    events, earnings_status = dependencies.earnings_loader(
        set(selected_symbols), started, config.request_timeout
    )
    events.attrs["status"] = earnings_status
    features = dependencies.feature_builder(
        selected_histories,
        selected_universe,
        benchmark,
        rankings,
        classified,
        pd.Timestamp(started),
    )
    features["benchmark_status"] = benchmark_status
    if benchmark_status != "COMPLETE" and "rs_line_eligibility" in features:
        features["rs_line_eligibility"] = RunStatus.INCOMPLETE.value
    matches = dependencies.screener_runner(features, events)

    valid_history_count = len(histories)
    historical_coverage = (
        valid_history_count / source_universe_count if source_universe_count else 0.0
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
        "schema_version": 2,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "market_state": market_state(started).value,
        "status": status.value,
        "outcome": outcome,
        "universe_source": UNIVERSE_URL,
        "price_source": YAHOO_SOURCE,
        "source_universe_count": source_universe_count,
        "universe_count": source_universe_count,
        "selected_universe_count": len(selected_universe),
        "recent_ipo_count": int(selected_universe["recent_ipo_overlay"].sum()),
        "valid_history_count": valid_history_count,
        "excluded_history_count": len(history_exclusions),
        "historical_coverage": round(historical_coverage, 6),
        "high_rs_count": high_rs_count,
        "valid_quote_count": valid_quote_count,
        "quote_coverage": round(quote_coverage, 6),
        "breakout_count": breakout_count,
        "benchmark_status": benchmark_status,
        "earnings_status": earnings_status,
        "screener_result_count": len(matches),
        "thresholds": {
            "high_rs": config.high_rs_threshold,
            "pivot_sessions": config.pivot_sessions,
            "coverage": config.coverage_threshold,
            "momentum_sessions": list(config.momentum_sessions),
            "momentum_weights": list(config.momentum_weights),
            "liquidity_count": config.liquidity_count,
            "liquidity_sessions": config.liquidity_sessions,
            "recent_ipo_days": config.recent_ipo_days,
        },
        "exclusion_reason_counts": dict(reason_counts),
    }
    artifacts = {
        "all_rankings.csv": rankings,
        "high_rs_setups.csv": classified,
        "live_breakouts.csv": breakouts,
        "exclusions.csv": exclusions,
        "chart_history.csv.gz": _chart_history(selected_histories, selected_symbols),
        "selected_universe.csv": selected_universe,
        "screener_features.csv": features,
        "screener_matches.csv": matches,
        "earnings_events.csv": events,
    }
    output_path = dependencies.publisher(output_root, artifacts, manifest)
    return ScanSummary(
        status,
        outcome,
        source_universe_count,
        valid_history_count,
        high_rs_count,
        valid_quote_count,
        breakout_count,
        started,
        finished,
        output_path,
    )
