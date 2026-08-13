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
            "listing_date": pd.to_datetime(["2020-01-01"] * universe_count),
            "yahoo_symbol": [f"S{i}.NS" for i in range(universe_count)],
        }
    )
    histories = {
        f"S{i}": pd.DataFrame(
            {
                "Open": [98.0] * 280,
                "High": [100.0] * 280,
                "Low": [97.0] * 280,
                "Close": [99.0] * 280,
                "Volume": [1_000_000] * 280,
            },
            index=pd.bdate_range(end="2026-08-11", periods=280),
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

    def universe_selector(source, available_histories, _now, _config):
        selected = source[source["symbol"].isin(available_histories)].copy()
        selected["median_traded_value_60d"] = 1_000_000.0
        selected["liquidity_rank"] = range(1, len(selected) + 1)
        selected["top_1000_liquid"] = True
        selected["recent_ipo_overlay"] = False
        return selected

    def feature_builder(
        _histories, selected, _benchmark, rankings, setups, as_of
    ):
        result = selected[["symbol", "company_name", "liquidity_rank"]].copy()
        result["scan_date"] = pd.Timestamp(as_of).date().isoformat()
        result["price_date"] = "2026-08-11"
        result["history_sessions"] = 280
        result["rs_rating"] = result["symbol"].map(
            rankings.set_index("symbol")["rs_rating"]
        )
        result["vcp_stars"] = result["symbol"].map(
            setups.set_index("symbol")["vcp_stars"]
        )
        return result

    def earnings_loader(_symbols, _as_of, _timeout):
        return pd.DataFrame(columns=["symbol", "event_type"]), "COMPLETE"

    def screener_runner(features, _events):
        result = features[["symbol"]].copy()
        result["screener"] = "nr7"
        result["state"] = "NO MATCH"
        return result

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
        benchmark_loader=lambda _now, _config: pd.DataFrame(
            {"Close": [100.0]}, index=pd.to_datetime(["2026-08-11"])
        ),
        universe_selector=universe_selector,
        feature_builder=feature_builder,
        earnings_loader=earnings_loader,
        screener_runner=screener_runner,
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


def test_schema_two_bundle_contains_expanded_screener_artifacts(tmp_path):
    dependencies, published = make_dependencies(high_rs_count=2)
    run_scan(ScanConfig(), dependencies, output_root=tmp_path)
    assert published["manifest"]["schema_version"] == 2
    assert {
        "selected_universe.csv",
        "screener_features.csv",
        "screener_matches.csv",
        "earnings_events.csv",
    } <= set(published["artifacts"])
    assert len(published["artifacts"]["high_rs_setups.csv"]) == 2
    assert set(published["artifacts"]["chart_history.csv.gz"]["symbol"]) == {
        f"S{index}" for index in range(10)
    }
