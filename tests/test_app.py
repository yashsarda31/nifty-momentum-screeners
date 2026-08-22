import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import app as dashboard_app
from app import (
    ENRICHED_BUNDLE_KEY,
    STARTUP_PRICES_KEY,
    RunBundleError,
    apply_startup_prices,
    build_price_figure,
    build_vcp_evidence,
    get_session_enriched_bundle,
    get_session_startup_prices,
    load_latest_run,
    render_vcp_stars,
    startup_price_summary,
    status_badge,
)
from nifty_vcp.dashboard_support import (
    clear_startup_price_state,
    scan_freshness,
)
from nifty_vcp.models import QuoteRecord, QuoteStatus
from nifty_vcp.startup_prices import StartupPriceSnapshot

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 8, 14, 10, 0, tzinfo=TZ)


def test_scan_freshness_marks_older_calendar_date_stale():
    freshness = scan_freshness(
        {"finished_at": "2026-08-20T16:00:00+05:30"},
        datetime(2026, 8, 22, 9, 0, tzinfo=TZ),
    )

    assert freshness.finished_at.isoformat() == "2026-08-20T16:00:00+05:30"
    assert freshness.age_days == 2
    assert freshness.is_stale is True
    assert freshness.label == "2 days old"


def test_scan_freshness_labels_same_day_current():
    freshness = scan_freshness(
        {"finished_at": "2026-08-22T08:00:00+05:30"},
        datetime(2026, 8, 22, 9, 0, tzinfo=TZ),
    )

    assert freshness.age_days == 0
    assert freshness.is_stale is False
    assert freshness.label == "today"


def test_scan_freshness_handles_missing_or_invalid_timestamp():
    missing = scan_freshness({}, datetime(2026, 8, 22, 9, 0, tzinfo=TZ))
    invalid = scan_freshness(
        {"finished_at": "not-a-date"},
        datetime(2026, 8, 22, 9, 0, tzinfo=TZ),
    )

    assert missing.finished_at is None
    assert missing.label == "scan time unavailable"
    assert invalid.finished_at is None
    assert invalid.is_stale is True


def test_clear_startup_price_state_preserves_unrelated_session_values():
    session = {
        STARTUP_PRICES_KEY: object(),
        ENRICHED_BUNDLE_KEY: object(),
        "screener_menu": "VCP",
    }

    clear_startup_price_state(
        session,
        STARTUP_PRICES_KEY,
        ENRICHED_BUNDLE_KEY,
    )

    assert STARTUP_PRICES_KEY not in session
    assert ENRICHED_BUNDLE_KEY not in session
    assert session["screener_menu"] == "VCP"


def startup_snapshot(
    price: float = 101.0, status: QuoteStatus = QuoteStatus.LIVE
) -> StartupPriceSnapshot:
    record = QuoteRecord("AAA", price, NOW, status, 0.0, "")
    return StartupPriceSnapshot(
        NOW,
        {"AAA": record},
        pd.DataFrame(
            {
                "symbol": ["AAA"],
                "latest_price": [price],
                "quote_timestamp": [NOW.isoformat()],
                "quote_status": [status.value],
                "quote_age_minutes": [0.0],
                "quote_reason": [""],
            }
        ),
    )


def test_missing_latest_returns_none(tmp_path):
    assert load_latest_run(tmp_path) is None


def write_schema_one_bundle(tmp_path, name="run-1"):
    run = tmp_path / name
    run.mkdir()
    (tmp_path / "latest.json").write_text(
        json.dumps({"run_directory": name}), encoding="utf-8"
    )
    (run / "run_manifest.json").write_text(
        json.dumps({"status": "COMPLETE"}), encoding="utf-8"
    )
    for filename in (
        "all_rankings.csv",
        "high_rs_setups.csv",
        "live_breakouts.csv",
        "exclusions.csv",
    ):
        pd.DataFrame({"symbol": ["AAA"]}).to_csv(run / filename, index=False)
    pd.DataFrame(
        {"symbol": ["AAA"], "date": ["2026-08-11"], "Close": [100.0]}
    ).to_csv(run / "chart_history.csv.gz", index=False, compression="gzip")
    return run


def test_latest_bundle_loads_manifest_and_stable_tables(tmp_path):
    write_schema_one_bundle(tmp_path)
    bundle = load_latest_run(tmp_path)
    assert bundle["manifest"]["status"] == "COMPLETE"
    assert bundle["rankings"].iloc[0]["symbol"] == "AAA"
    assert str(bundle["chart_history"]["date"].dtype).startswith("datetime64")
    assert bundle["screeners_available"] is False


def test_latest_pointer_cannot_escape_output_root(tmp_path):
    (tmp_path / "latest.json").write_text(
        json.dumps({"run_directory": "../outside"}), encoding="utf-8"
    )

    with pytest.raises(RunBundleError, match="outside the output root"):
        load_latest_run(tmp_path)


def test_malformed_latest_pointer_has_controlled_error(tmp_path):
    (tmp_path / "latest.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(RunBundleError, match="latest.json"):
        load_latest_run(tmp_path)


def test_missing_required_artifact_has_controlled_error(tmp_path):
    run = tmp_path / "run-missing"
    run.mkdir()
    (tmp_path / "latest.json").write_text(
        json.dumps({"run_directory": "run-missing"}), encoding="utf-8"
    )
    (run / "run_manifest.json").write_text(
        json.dumps({"status": "COMPLETE"}), encoding="utf-8"
    )

    with pytest.raises(RunBundleError, match="all_rankings.csv"):
        load_latest_run(tmp_path)


def test_partial_schema_two_bundle_reports_why_screeners_are_unavailable(tmp_path):
    run = write_schema_one_bundle(tmp_path, "run-partial")
    manifest = {"status": "COMPLETE", "schema_version": 2}
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    pd.DataFrame({"symbol": ["AAA"]}).to_csv(
        run / "selected_universe.csv", index=False
    )

    bundle = load_latest_run(tmp_path)

    assert bundle["screeners_available"] is False
    assert "screener_features.csv" in bundle["screeners_unavailable_reason"]


def test_schema_two_bundle_loads_screener_tables(tmp_path):
    run = tmp_path / "run-2"
    run.mkdir()
    (tmp_path / "latest.json").write_text(
        json.dumps({"run_directory": "run-2"}), encoding="utf-8"
    )
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "status": "COMPLETE",
                "earnings_status": "COMPLETE",
            }
        ),
        encoding="utf-8",
    )
    standard = [
        "all_rankings.csv",
        "high_rs_setups.csv",
        "live_breakouts.csv",
        "exclusions.csv",
    ]
    for name in standard:
        pd.DataFrame({"symbol": ["AAA"]}).to_csv(run / name, index=False)
    pd.DataFrame(
        {"symbol": ["AAA"], "date": ["2026-08-11"], "Close": [100.0]}
    ).to_csv(run / "chart_history.csv.gz", index=False, compression="gzip")
    pd.DataFrame({"symbol": ["AAA"], "liquidity_rank": [1]}).to_csv(
        run / "selected_universe.csv", index=False
    )
    pd.DataFrame({"symbol": ["AAA"], "gap_pct": [4.0]}).to_csv(
        run / "screener_features.csv", index=False
    )
    pd.DataFrame({"symbol": ["AAA"], "screener": ["gap_up"]}).to_csv(
        run / "screener_matches.csv", index=False
    )
    pd.DataFrame({"symbol": ["AAA"], "event_type": ["RESULTS_DUE"]}).to_csv(
        run / "earnings_events.csv", index=False
    )
    bundle = load_latest_run(tmp_path)
    assert bundle["screeners_available"] is True
    assert bundle["features"].iloc[0]["symbol"] == "AAA"
    assert bundle["earnings"].attrs["status"] == "COMPLETE"


def test_star_and_status_markup_has_text_not_color_only():
    stars = render_vcp_stars(3)
    assert "★★★☆☆" in stars
    assert "3 of 5" in stars
    assert "SCAN INCOMPLETE" in status_badge("SCAN INCOMPLETE")


def test_price_figure_contains_candlestick_volume_mas_and_pivot():
    close = pd.Series(range(100, 400), dtype=float)
    frame = pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-01", periods=300),
            "Open": close - 1,
            "High": close + 2,
            "Low": close - 2,
            "Close": close,
            "Volume": 1_000_000,
        }
    )
    figure = build_price_figure(frame, pivot=390.0)
    names = {trace.name for trace in figure.data}
    assert {"Price", "Volume", "SMA 50", "SMA 150", "SMA 200"} <= names
    assert any(shape.type == "line" for shape in figure.layout.shapes)


def test_vcp_evidence_values_are_arrow_safe_strings():
    evidence = build_vcp_evidence(
        pd.Series({"vcp_stars": 4, "vcp_trend_template": True})
    )
    assert evidence["value"].map(type).eq(str).all()


def test_rs_leaders_table_shows_sortable_vcp_rating_out_of_five(monkeypatch):
    captured = {}

    def capture_dataframe(data, **kwargs):
        captured["data"] = data
        captured["kwargs"] = kwargs

    monkeypatch.setattr(dashboard_app.st, "dataframe", capture_dataframe)
    renderer = getattr(dashboard_app, "render_rs_leaders_table", None)
    assert callable(renderer)

    renderer(
        pd.DataFrame(
            {
                "company_name": ["One Limited", "Two Limited"],
                "vcp_stars": ["2", "5"],
                "symbol": ["ONE", "TWO"],
                "rs_rating": [90, 95],
                "latest_close": [100.0, 200.0],
            }
        )
    )

    table = captured["data"]
    assert table.columns[:4].tolist() == [
        "symbol",
        "company_name",
        "rs_rating",
        "vcp_stars",
    ]
    assert table.sort_values("vcp_stars", ascending=False)["symbol"].tolist() == [
        "TWO",
        "ONE",
    ]
    config = captured["kwargs"]["column_config"]["vcp_stars"]
    assert config["label"] == "VCP rating"
    assert config["type_config"]["format"] == "%d / 5"
    assert config["type_config"]["min_value"] == 0
    assert config["type_config"]["max_value"] == 5


def test_tradingview_export_renders_copy_text_table_and_download(monkeypatch):
    captured = {}
    monkeypatch.setattr(dashboard_app.st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard_app.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        dashboard_app.st, "number_input", lambda *args, **kwargs: 10.0
    )
    monkeypatch.setattr(
        dashboard_app.st,
        "dataframe",
        lambda data, **kwargs: captured.update(table=data, dataframe_kwargs=kwargs),
    )
    monkeypatch.setattr(
        dashboard_app.st,
        "code",
        lambda body, **kwargs: captured.update(copy_text=body, code_kwargs=kwargs),
    )
    monkeypatch.setattr(
        dashboard_app.st,
        "download_button",
        lambda **kwargs: captured.update(download=kwargs),
    )
    renderer = getattr(dashboard_app, "render_tradingview_export", None)
    assert callable(renderer)

    renderer(
        pd.DataFrame(
            {
                "symbol": ["AAA", "BBB"],
                "company_name": ["A Limited", "B Limited"],
                "rs_rating": [99, 98],
                "vcp_stars": [5, 4],
                "median_traded_value_60d": [200_000_000, 150_000_000],
                "top_1000_liquid": [True, True],
                "is_high_rs": [True, True],
                "history_status": ["COMPLETE", "COMPLETE"],
            }
        )
    )

    assert captured["table"]["symbol"].tolist() == ["AAA", "BBB"]
    assert captured["copy_text"] == "NSE:AAA,NSE:BBB"
    assert captured["code_kwargs"]["language"] is None
    assert captured["download"]["data"] == "NSE:AAA,NSE:BBB"
    assert captured["download"]["file_name"] == "nifty_top25_tradingview.txt"
    assert captured["download"]["on_click"] == "ignore"


def test_stock_table_prioritizes_and_labels_session_fresh_yahoo_quote(monkeypatch):
    captured = {}

    def capture_dataframe(data, **kwargs):
        captured["data"] = data
        captured["kwargs"] = kwargs

    monkeypatch.setattr(dashboard_app.st, "dataframe", capture_dataframe)
    renderer = getattr(dashboard_app, "render_stock_table", None)
    assert callable(renderer)

    renderer(
        pd.DataFrame(
            {
                "price_date": ["2026-08-12"],
                "latest_close": [100.0],
                "symbol": ["AAA"],
                "latest_price": [105.0],
                "quote_timestamp": ["2026-08-14T15:15:00+05:30"],
                "quote_status": ["LAST AVAILABLE"],
                "price_change_pct": [5.0],
            }
        )
    )

    assert captured["data"].columns[:7].tolist() == [
        "symbol",
        "latest_price",
        "quote_timestamp",
        "quote_status",
        "price_change_pct",
        "latest_close",
        "price_date",
    ]
    config = captured["kwargs"]["column_config"]
    assert config["latest_price"]["label"] == "Latest Yahoo price"
    assert config["quote_timestamp"]["label"] == "Yahoo quote time"
    assert config["latest_close"]["label"] == "Scan close"
    assert config["price_date"] == "Completed candle date"


def test_startup_prices_fetch_once_per_session_and_refetch_for_new_session():
    calls = []
    universe = pd.DataFrame(
        {"symbol": ["AAA"], "yahoo_symbol": ["AAA.NS"]}
    )

    def fetcher(selected):
        calls.append(selected["symbol"].tolist())
        return startup_snapshot()

    first_session = {}
    first = get_session_startup_prices(first_session, "run-1", universe, fetcher)
    second = get_session_startup_prices(first_session, "run-1", universe, fetcher)
    refreshed = get_session_startup_prices({}, "run-1", universe, fetcher)

    assert first is second
    assert refreshed is not None
    assert calls == [["AAA"], ["AAA"]]


def test_startup_prices_refetch_when_scan_bundle_changes():
    calls = []
    universe = pd.DataFrame(
        {"symbol": ["AAA"], "yahoo_symbol": ["AAA.NS"]}
    )

    def fetcher(selected):
        calls.append(selected["symbol"].tolist())
        return startup_snapshot()

    session = {}
    get_session_startup_prices(session, "run-1", universe, fetcher)
    get_session_startup_prices(session, "run-2", universe, fetcher)

    assert len(calls) == 2


def test_quote_enrichment_runs_once_per_session_and_scan_bundle():
    calls = []
    session = {}
    snapshot = startup_snapshot()

    def enricher(bundle, received_snapshot):
        calls.append((bundle["run"], received_snapshot.fetched_at))
        return {**bundle, "enriched": True}

    first = get_session_enriched_bundle(
        session, "run-1", {"run": 1}, snapshot, enricher
    )
    second = get_session_enriched_bundle(
        session, "run-1", {"run": 1}, snapshot, enricher
    )
    refreshed = get_session_enriched_bundle(
        session, "run-2", {"run": 2}, snapshot, enricher
    )

    assert first is second
    assert first["enriched"] is True
    assert refreshed["run"] == 2
    assert [run for run, _ in calls] == [1, 2]


def test_apply_startup_prices_updates_tables_and_live_breakouts_in_memory():
    dates = pd.bdate_range("2026-05-22", periods=60)
    history = pd.DataFrame(
        {
            "symbol": "AAA",
            "date": dates,
            "Open": 99.0,
            "High": 100.0,
            "Low": 98.0,
            "Close": 99.0,
            "Volume": 1_000_000.0,
        }
    )
    bundle = {
        "manifest": {"thresholds": {"pivot_sessions": 55}},
        "rankings": pd.DataFrame(
            {"symbol": ["AAA"], "latest_close": [100.0]}
        ),
        "setups": pd.DataFrame(
            {"symbol": ["AAA"], "latest_close": [100.0], "pivot_55": [100.0]}
        ),
        "features": pd.DataFrame(
            {"symbol": ["AAA"], "latest_close": [100.0]}
        ),
        "breakouts": pd.DataFrame(),
        "chart_history": history,
    }

    updated = apply_startup_prices(bundle, startup_snapshot())

    assert "latest_price" not in bundle["rankings"]
    assert updated["rankings"].iloc[0]["latest_close"] == 100.0
    assert updated["rankings"].iloc[0]["latest_price"] == 101.0
    assert updated["rankings"].iloc[0]["price_change_pct"] == pytest.approx(1.0)
    assert updated["features"].iloc[0]["quote_status"] == "LIVE"
    assert bool(updated["setups"].iloc[0]["is_breakout"])
    assert updated["breakouts"]["symbol"].tolist() == ["AAA"]
    assert updated["startup_prices"].fetched_at == NOW


def test_apply_startup_prices_does_not_confirm_delayed_breakout():
    dates = pd.bdate_range("2026-05-22", periods=60)
    bundle = {
        "manifest": {"thresholds": {"pivot_sessions": 55}},
        "rankings": pd.DataFrame(
            {"symbol": ["AAA"], "latest_close": [100.0]}
        ),
        "setups": pd.DataFrame(
            {"symbol": ["AAA"], "latest_close": [100.0]}
        ),
        "features": pd.DataFrame(
            {"symbol": ["AAA"], "latest_close": [100.0]}
        ),
        "breakouts": pd.DataFrame(),
        "chart_history": pd.DataFrame(
            {
                "symbol": "AAA",
                "date": dates,
                "High": 100.0,
                "Close": 99.0,
            }
        ),
    }

    updated = apply_startup_prices(
        bundle, startup_snapshot(101.0, QuoteStatus.DELAYED)
    )

    assert not bool(updated["setups"].iloc[0]["is_breakout"])
    assert updated["breakouts"].empty


def test_startup_price_summary_reports_fetched_coverage():
    snapshot = startup_snapshot()
    unavailable = pd.DataFrame(
        {
            "symbol": ["MISS"],
            "latest_price": [None],
            "quote_timestamp": [""],
            "quote_status": ["UNAVAILABLE"],
            "quote_age_minutes": [None],
            "quote_reason": ["provider failure"],
        }
    )
    snapshot = StartupPriceSnapshot(
        snapshot.fetched_at,
        snapshot.quotes,
        pd.concat([snapshot.table, unavailable], ignore_index=True),
    )

    summary = startup_price_summary(snapshot)

    assert summary == {
        "fetched_at": NOW.isoformat(),
        "usable_count": 1,
        "total_count": 2,
        "coverage": 0.5,
    }
