"""Pure helpers for dashboard freshness, health, and session state."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ScanFreshness:
    """Display-ready age information for one persisted scan."""

    finished_at: datetime | None
    age_days: int | None
    label: str
    is_stale: bool


def scan_freshness(manifest: dict, now: datetime) -> ScanFreshness:
    """Describe scan age without implying that newer quotes refresh its signals."""
    raw = manifest.get("finished_at")
    try:
        parsed = pd.Timestamp(raw)
    except (TypeError, ValueError):
        return ScanFreshness(None, None, "scan time unavailable", True)
    if pd.isna(parsed):
        return ScanFreshness(None, None, "scan time unavailable", True)
    finished = parsed.to_pydatetime()
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=now.tzinfo)
    local_now = now.astimezone(finished.tzinfo)
    age_days = max(0, (local_now.date() - finished.date()).days)
    if age_days == 0:
        label = "today"
    elif age_days == 1:
        label = "1 day old"
    else:
        label = f"{age_days} days old"
    return ScanFreshness(finished, age_days, label, age_days > 1)


def clear_startup_price_state(
    session_state: MutableMapping[str, Any],
    startup_key: str,
    enriched_key: str,
) -> None:
    """Invalidate only the session's fetched and derived quote snapshots."""
    session_state.pop(startup_key, None)
    session_state.pop(enriched_key, None)


def _coverage(valid: object, total: object) -> float:
    try:
        valid_count = int(valid)
        total_count = int(total)
    except (TypeError, ValueError):
        return 0.0
    return valid_count / total_count if total_count > 0 else 0.0


def _manifest_coverage(
    manifest: dict,
    key: str,
    valid_key: str,
    total_key: str,
    *,
    empty_total: float = 0.0,
) -> float:
    raw = manifest.get(key)
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    total = manifest.get(total_key)
    try:
        if int(total or 0) == 0:
            return empty_total
    except (TypeError, ValueError):
        return empty_total
    return _coverage(manifest.get(valid_key), total)


def scan_health_summary(manifest: dict, exclusions: pd.DataFrame) -> dict[str, Any]:
    """Build audit-friendly coverage, timing, provider, and exclusion data."""
    required = {"stage", "reason"}
    if exclusions.empty or not required <= set(exclusions):
        groups = pd.DataFrame(columns=["stage", "reason", "count"])
    else:
        source = exclusions.loc[:, ["stage", "reason"]].fillna("unknown")
        groups = (
            source.groupby(["stage", "reason"], dropna=False)
            .size()
            .rename("count")
            .reset_index()
            .sort_values(
                ["stage", "count", "reason"], ascending=[True, False, True]
            )
            .reset_index(drop=True)
        )

    started = pd.to_datetime(manifest.get("started_at"), errors="coerce")
    finished = pd.to_datetime(manifest.get("finished_at"), errors="coerce")
    elapsed = None
    if pd.notna(started) and pd.notna(finished):
        elapsed = max(0.0, (finished - started).total_seconds())

    return {
        "status": str(manifest.get("status", "UNKNOWN")),
        "historical_coverage": _manifest_coverage(
            manifest,
            "historical_coverage",
            "valid_history_count",
            "universe_count",
        ),
        "quote_coverage": _manifest_coverage(
            manifest,
            "quote_coverage",
            "valid_quote_count",
            "high_rs_count",
            empty_total=1.0,
        ),
        "providers": {
            "Benchmark": str(manifest.get("benchmark_status", "UNKNOWN")),
            "Earnings": str(manifest.get("earnings_status", "UNKNOWN")),
        },
        "started_at": None if pd.isna(started) else started.isoformat(),
        "finished_at": None if pd.isna(finished) else finished.isoformat(),
        "elapsed_seconds": elapsed,
        "market_state": str(manifest.get("market_state", "UNKNOWN")),
        "exclusion_groups": groups,
    }
