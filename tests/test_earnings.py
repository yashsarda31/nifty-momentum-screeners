import pandas as pd

from nifty_vcp.earnings import (
    BOARD_MEETINGS_URL,
    INTEGRATED_RESULTS_URL,
    fetch_earnings_events,
    parse_board_meetings,
    parse_financial_results,
)


def test_parse_board_meetings_keeps_financial_results_only():
    rows = [
        {
            "bm_symbol": "AAA",
            "bm_purpose": "Board Meeting Intimation",
            "bm_desc": "To consider and approve the Unaudited Financial results",
            "bm_date": "20-Aug-2026",
        },
        {
            "bm_symbol": "BBB",
            "bm_purpose": "Dividend",
            "bm_desc": "To consider dividend",
            "bm_date": "21-Aug-2026",
        },
    ]
    result = parse_board_meetings(rows, BOARD_MEETINGS_URL)
    assert result[["symbol", "event_type"]].to_dict("records") == [
        {"symbol": "AAA", "event_type": "RESULTS_DUE"}
    ]
    assert result.iloc[0]["event_date"] == pd.Timestamp("2026-08-20")


def test_parse_integrated_financial_results_normalizes_broadcast_time():
    result = parse_financial_results(
        [{"symbol": "AAA", "broadcast_Date": "12-Aug-2026 18:30:00"}],
        INTEGRATED_RESULTS_URL,
    )
    assert result.iloc[0]["event_type"] == "RESULT_FILED"
    assert result.iloc[0]["broadcast_at"].tzinfo is not None
    assert str(result.iloc[0]["broadcast_at"].tzinfo) == "Asia/Kolkata"


def test_fetch_filters_symbols_and_uses_bounded_official_endpoints():
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.urls = []

        def get(self, url, **_kwargs):
            self.urls.append(url)
            if url == "https://www.nseindia.com/":
                return Response({})
            if "corporate-board-meetings" in url:
                return Response(
                    [
                        {
                            "bm_symbol": "AAA",
                            "bm_purpose": "Financial Results",
                            "bm_desc": "Financial Results",
                            "bm_date": "20-Aug-2026",
                        },
                        {
                            "bm_symbol": "OUT",
                            "bm_purpose": "Financial Results",
                            "bm_desc": "Financial Results",
                            "bm_date": "20-Aug-2026",
                        },
                    ]
                )
            return Response(
                {
                    "data": [
                        {
                            "symbol": "AAA",
                            "broadcast_Date": "12-Aug-2026 18:30:00",
                        }
                    ],
                    "totalCount": 1,
                }
            )

    session = Session()
    events, status = fetch_earnings_events(
        {"AAA"}, pd.Timestamp("2026-08-13", tz="Asia/Kolkata"), session=session
    )
    assert status == "COMPLETE"
    assert set(events["symbol"]) == {"AAA"}
    assert {event for event in events["event_type"]} == {
        "RESULTS_DUE",
        "RESULT_FILED",
    }
    assert any("to_date=27-08-2026" in url for url in session.urls)
    assert any("from_date=30-07-2026" in url for url in session.urls)


def test_fetch_failure_returns_empty_frame_and_incomplete_status():
    class FailingSession:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("blocked")

    events, status = fetch_earnings_events(
        {"AAA"},
        pd.Timestamp("2026-08-13", tz="Asia/Kolkata"),
        session=FailingSession(),
    )
    assert events.empty
    assert list(events.columns) == [
        "symbol",
        "event_type",
        "event_date",
        "broadcast_at",
        "source_url",
    ]
    assert status == "SCAN INCOMPLETE"
