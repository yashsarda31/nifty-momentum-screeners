from pathlib import Path

import pandas as pd

from screener_ui import render_screeners

features = pd.DataFrame(
    {
        "symbol": ["AAA"],
        "company_name": ["AAA Limited"],
        "listing_date": ["2025-01-01"],
        "liquidity_rank": [1],
        "price_date": ["2026-08-13"],
        "scan_date": ["2026-08-13"],
        "history_sessions": [280],
        "gap_pct": [4.0],
        "latest_price": [105.0],
        "price_change_pct": [5.0],
        "quote_status": ["LIVE"],
        "quote_timestamp": ["2026-08-14T10:00:00+05:30"],
    }
)
events = pd.DataFrame(columns=["symbol", "event_type", "event_date", "broadcast_at"])
events.attrs["status"] = "COMPLETE"
render_screeners(
    {
        "screeners_available": True,
        "features": features,
        "matches": pd.DataFrame(),
        "earnings": events,
        "chart_history": pd.DataFrame(),
        "manifest": {"status": "COMPLETE"},
    },
    Path("tests/.custom_screeners_fixture.json"),
)
