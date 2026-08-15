"""Session-start quote snapshots and display-only price enrichment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from nifty_vcp.market_data import collect_startup_quotes
from nifty_vcp.models import QuoteRecord, QuoteStatus, ScanConfig
from nifty_vcp.sessions import INDIA_TZ

QUOTE_DISPLAY_COLUMNS = (
    "latest_price",
    "quote_timestamp",
    "quote_status",
    "quote_age_minutes",
    "quote_reason",
    "price_change_pct",
)


@dataclass(frozen=True)
class StartupPriceSnapshot:
    """Latest available quotes fetched for one Streamlit browser session."""

    fetched_at: datetime
    quotes: dict[str, QuoteRecord]
    table: pd.DataFrame


def fetch_startup_prices(
    universe: pd.DataFrame,
    now: datetime | None = None,
    config: ScanConfig | None = None,
    quote_loader: Callable = collect_startup_quotes,
) -> StartupPriceSnapshot:
    """Fetch and normalize one quote row for every selected symbol."""
    fetched_at = now or datetime.now(tz=INDIA_TZ)
    quotes, _ = quote_loader(
        universe,
        now=fetched_at,
        config=config or ScanConfig(),
    )
    rows = []
    for item in universe.itertuples(index=False):
        record = quotes.get(
            item.symbol,
            QuoteRecord(
                item.symbol,
                None,
                None,
                QuoteStatus.UNAVAILABLE,
                None,
                "quote unavailable",
            ),
        )
        rows.append(
            {
                "symbol": item.symbol,
                "latest_price": record.price,
                "quote_timestamp": (
                    record.timestamp.isoformat() if record.timestamp else ""
                ),
                "quote_status": record.status.value,
                "quote_age_minutes": record.age_minutes,
                "quote_reason": record.reason,
            }
        )
    columns = ["symbol", *QUOTE_DISPLAY_COLUMNS[:-1]]
    return StartupPriceSnapshot(
        fetched_at,
        quotes,
        pd.DataFrame(rows, columns=columns),
    )


def attach_startup_prices(
    frame: pd.DataFrame,
    quote_table: pd.DataFrame,
    close_column: str = "latest_close",
) -> pd.DataFrame:
    """Left-join startup quotes without changing the completed daily close."""
    stale_columns = [
        column for column in QUOTE_DISPLAY_COLUMNS if column in frame.columns
    ]
    base = frame.drop(columns=stale_columns).copy()
    result = base.merge(quote_table, on="symbol", how="left", validate="many_to_one")
    latest = pd.to_numeric(result.get("latest_price"), errors="coerce")
    completed = pd.to_numeric(result.get(close_column), errors="coerce")
    valid = (
        np.isfinite(latest)
        & np.isfinite(completed)
        & latest.gt(0)
        & completed.gt(0)
    )
    result["price_change_pct"] = np.where(
        valid,
        (latest / completed - 1.0) * 100.0,
        np.nan,
    )
    return result
