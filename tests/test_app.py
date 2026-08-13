import json

import pandas as pd

from app import (
    build_price_figure,
    build_vcp_evidence,
    load_latest_run,
    render_vcp_stars,
    status_badge,
)


def test_missing_latest_returns_none(tmp_path):
    assert load_latest_run(tmp_path) is None


def test_latest_bundle_loads_manifest_and_stable_tables(tmp_path):
    run = tmp_path / "run-1"
    run.mkdir()
    (tmp_path / "latest.json").write_text(
        json.dumps({"run_directory": "run-1"}), encoding="utf-8"
    )
    (run / "run_manifest.json").write_text(
        json.dumps({"status": "COMPLETE"}), encoding="utf-8"
    )
    for name in [
        "all_rankings.csv",
        "high_rs_setups.csv",
        "live_breakouts.csv",
        "exclusions.csv",
    ]:
        pd.DataFrame({"symbol": ["AAA"]}).to_csv(run / name, index=False)
    pd.DataFrame(
        {"symbol": ["AAA"], "date": ["2026-08-11"], "Close": [100.0]}
    ).to_csv(run / "chart_history.csv.gz", index=False, compression="gzip")
    bundle = load_latest_run(tmp_path)
    assert bundle["manifest"]["status"] == "COMPLETE"
    assert bundle["rankings"].iloc[0]["symbol"] == "AAA"
    assert str(bundle["chart_history"]["date"].dtype).startswith("datetime64")
    assert bundle["screeners_available"] is False


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
