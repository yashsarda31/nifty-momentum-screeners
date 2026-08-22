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
