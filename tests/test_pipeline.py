from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from nifty_vcp.models import QuoteRecord, QuoteStatus, RunStatus, ScanConfig
from nifty_vcp.pipeline import PipelineDependencies, run_scan

TZ = ZoneInfo("Asia/Kolkata")


def make_dependencies(
    universe_count=10, history_count=10, high_rs_count=2, valid_quote_count=2
):
    universe = pd.DataFrame(
        {
            "symbol": [f"S{i}" for i in range(universe_count)],
            "company_name": [f"Stock {i}" for i in range(universe_count)],
            "industry": ["Test"] * universe_count,
            "yahoo_symbol": [f"S{i}.NS" for i in range(universe_count)],
        }
    )
    histories = {
        f"S{i}": pd.DataFrame(
            {"High": [100.0], "Close": [99.0]},
            index=pd.to_datetime(["2026-08-11"]),
        )
        for i in range(history_count)
    }
    history_exclusions = {
        f"S{i}": "history missing" for i in range(history_count, universe_count)
    }

    def ranker(_histories, valid_universe, _config):
        rows = valid_universe.iloc[:history_count].copy()
        rows["rs_rating"] = [99 - i for i in range(history_count)]
        rows["is_high_rs"] = [i < high_rs_count for i in range(history_count)]
        rows["weighted_momentum"] = 1.0
        return rows

    def scorer(_histories, rankings, _config):
        result = rankings[rankings["is_high_rs"]].copy()
        result["vcp_stars"] = 4
        return result

    def quote_loader(symbols, _now, _config):
        quotes = {}
        exclusions = {}
        for index, symbol in enumerate(symbols["symbol"]):
            if index < valid_quote_count:
                quotes[symbol] = QuoteRecord(
                    symbol,
                    101.0,
                    datetime(2026, 8, 12, 10, 0, tzinfo=TZ),
                    QuoteStatus.LIVE,
                    0.0,
                    "",
                )
            else:
                quotes[symbol] = QuoteRecord(
                    symbol, None, None, QuoteStatus.UNAVAILABLE, None, "missing"
                )
                exclusions[symbol] = "missing"
        return quotes, exclusions

    def classifier(setups, _histories, quotes, _sessions):
        result = setups.copy()
        result["live_price"] = result["symbol"].map(
            lambda symbol: quotes[symbol].price
        )
        result["is_breakout"] = False
        result["quote_status"] = result["symbol"].map(
            lambda symbol: quotes[symbol].status.value
        )
        return result

    published = {}

    def publisher(output_root, artifacts, manifest):
        published["artifacts"] = artifacts
        published["manifest"] = manifest
        return Path(output_root) / "fake-run"

    dependencies = PipelineDependencies(
        universe_loader=lambda _timeout: universe,
        daily_loader=lambda _universe, _now, _config: (
            histories,
            history_exclusions,
        ),
        quote_loader=quote_loader,
        ranker=ranker,
        scorer=scorer,
        classifier=classifier,
        publisher=publisher,
    )
    return dependencies, published


def test_complete_at_exactly_ninety_percent_historical_coverage(tmp_path):
    dependencies, published = make_dependencies(
        universe_count=10, history_count=9, high_rs_count=2, valid_quote_count=2
    )
    summary = run_scan(
        ScanConfig(), dependencies, datetime(2026, 8, 12, 10, 0, tzinfo=TZ), tmp_path
    )
    assert summary.status == RunStatus.COMPLETE
    assert summary.outcome == "NO BREAKOUTS"
    assert published["manifest"]["historical_coverage"] == 0.9


def test_below_historical_coverage_is_incomplete(tmp_path):
    dependencies, _ = make_dependencies(universe_count=10, history_count=8)
    summary = run_scan(ScanConfig(), dependencies, output_root=tmp_path)
    assert summary.status == RunStatus.INCOMPLETE
    assert summary.outcome == "SCAN INCOMPLETE"


def test_below_quote_coverage_is_incomplete_and_not_no_breakouts(tmp_path):
    dependencies, published = make_dependencies(
        universe_count=10, history_count=10, high_rs_count=10, valid_quote_count=8
    )
    summary = run_scan(ScanConfig(), dependencies, output_root=tmp_path)
    assert summary.status == RunStatus.INCOMPLETE
    assert summary.outcome == "SCAN INCOMPLETE"
    assert published["manifest"]["quote_coverage"] == 0.8


def test_low_rs_stocks_do_not_enter_quote_or_vcp_steps(tmp_path):
    dependencies, published = make_dependencies(high_rs_count=2)
    run_scan(ScanConfig(), dependencies, output_root=tmp_path)
    assert len(published["artifacts"]["high_rs_setups.csv"]) == 2
    assert set(published["artifacts"]["chart_history.csv.gz"]["symbol"]) == {
        "S0",
        "S1",
    }
