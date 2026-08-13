"""Official NSE board-meeting and integrated financial-result events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import pandas as pd
import requests

from nifty_vcp.sessions import INDIA_TZ

NSE_HOME = "https://www.nseindia.com/"
BOARD_MEETINGS_URL = "https://www.nseindia.com/api/corporate-board-meetings"
INTEGRATED_RESULTS_URL = "https://www.nseindia.com/api/integrated-filing-results"
USER_AGENT = "Mozilla/5.0 (compatible; NiftyVCPResearch/0.2)"
EVENT_COLUMNS = [
    "symbol",
    "event_type",
    "event_date",
    "broadcast_at",
    "source_url",
]


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=EVENT_COLUMNS)


def parse_board_meetings(
    rows: Iterable[Mapping], source_url: str = BOARD_MEETINGS_URL
) -> pd.DataFrame:
    records = []
    for row in rows:
        symbol = str(row.get("bm_symbol", row.get("symbol", ""))).strip().upper()
        purpose = str(row.get("bm_purpose", row.get("purpose", "")))
        description = str(row.get("bm_desc", row.get("description", "")))
        if not symbol or "financial result" not in f"{purpose} {description}".lower():
            continue
        raw_date = row.get("bm_date", row.get("date"))
        event_date = pd.to_datetime(raw_date, format="%d-%b-%Y", errors="raise")
        records.append(
            {
                "symbol": symbol,
                "event_type": "RESULTS_DUE",
                "event_date": event_date.normalize(),
                "broadcast_at": pd.NaT,
                "source_url": source_url,
            }
        )
    return pd.DataFrame(records, columns=EVENT_COLUMNS)


def parse_financial_results(
    rows: Iterable[Mapping], source_url: str = INTEGRATED_RESULTS_URL
) -> pd.DataFrame:
    records = []
    for row in rows:
        symbol = str(row.get("symbol", row.get("sm_symbol", ""))).strip().upper()
        raw_broadcast = row.get(
            "broadcast_Date", row.get("broadcastDateTime", row.get("broadcast_date"))
        )
        if not symbol or not raw_broadcast:
            continue
        broadcast = pd.to_datetime(raw_broadcast, format="%d-%b-%Y %H:%M:%S", errors="raise")
        broadcast = broadcast.tz_localize(INDIA_TZ)
        records.append(
            {
                "symbol": symbol,
                "event_type": "RESULT_FILED",
                "event_date": broadcast.tz_localize(None).normalize(),
                "broadcast_at": broadcast,
                "source_url": source_url,
            }
        )
    return pd.DataFrame(records, columns=EVENT_COLUMNS)


def _date(value: pd.Timestamp) -> str:
    return value.strftime("%d-%m-%Y")


def fetch_earnings_events(
    symbols: set[str],
    as_of: pd.Timestamp,
    timeout: float = 20.0,
    session: requests.Session | None = None,
) -> tuple[pd.DataFrame, str]:
    client = session or requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar",
    }
    current = pd.Timestamp(as_of)
    if current.tzinfo is not None:
        current = current.tz_convert(INDIA_TZ).tz_localize(None)
    current = current.normalize()
    try:
        client.get(NSE_HOME, headers=headers, timeout=timeout)
        board_url = (
            f"{BOARD_MEETINGS_URL}?index=equities&from_date={_date(current)}"
            f"&to_date={_date(current + pd.Timedelta(days=14))}"
        )
        result_url = (
            f"{INTEGRATED_RESULTS_URL}?type=Integrated%20Filing-%20Financials"
            f"&from_date={_date(current - pd.Timedelta(days=14))}"
            f"&to_date={_date(current)}&index=equities&page=1&size=2000"
        )
        board_response = client.get(board_url, headers=headers, timeout=timeout)
        result_response = client.get(result_url, headers=headers, timeout=timeout)
        board_response.raise_for_status()
        result_response.raise_for_status()
        board_payload = board_response.json()
        result_payload = result_response.json()
        board_rows = board_payload.get("data", []) if isinstance(board_payload, dict) else board_payload
        result_rows = result_payload.get("data", []) if isinstance(result_payload, dict) else result_payload
        events = pd.concat(
            [
                parse_board_meetings(board_rows, BOARD_MEETINGS_URL),
                parse_financial_results(result_rows, INTEGRATED_RESULTS_URL),
            ],
            ignore_index=True,
        )
        if events.empty:
            return _empty_events(), "COMPLETE"
        events = events[events["symbol"].isin({symbol.upper() for symbol in symbols})]
        events = events.drop_duplicates(
            ["symbol", "event_type", "event_date"], keep="first"
        )
        return events.sort_values(
            ["event_date", "symbol", "event_type"], ignore_index=True
        ), "COMPLETE"
    except Exception:  # noqa: BLE001 - provider/schema diagnostics become run status
        return _empty_events(), "SCAN INCOMPLETE"
