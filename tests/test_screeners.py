import pandas as pd

from nifty_vcp.screeners import (
    SCREENER_CATALOG,
    default_thresholds,
    evaluate_all_screeners,
    evaluate_screener,
    multiple_scan_matches,
)

EXPECTED = {
    "horizontal_resistance",
    "nr7",
    "three_tight_closes",
    "atr_contraction",
    "ipo_base",
    "ipo_momentum",
    "ipo_breakout",
    "rs_high_before_price_high",
    "momentum",
    "relative_volume_surge",
    "accumulation_day",
    "volume_dry_up",
    "vcp",
    "flags_pennants",
    "results_due",
    "fresh_results",
    "post_results_gap_up",
    "gap_up",
    "gap_down",
    "gap_and_hold",
    "daily_inside_bar",
    "double_inside_bar",
    "weekly_inside_bar",
}


def matching_features():
    base = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "company_name": ["AAA Limited"],
            "listing_date": ["2026-01-01"],
            "liquidity_rank": [1],
            "price_date": ["2026-08-13"],
            "scan_date": ["2026-08-13"],
            "history_sessions": [280],
            "resistance_touches": [3],
            "resistance_dispersion_pct": [1.0],
            "distance_to_resistance_pct": [2.0],
            "nr7": [True],
            "three_close_band_pct": [1.5],
            "atr14_pct": [2.0],
            "atr14_average_50_pct": [2.1],
            "recent_ipo_overlay": [True],
            "ipo_base_depth_pct": [20.0],
            "latest_close": [110.0],
            "sma20": [100.0],
            "return_20d": [10.0],
            "prior_20_high": [109.0],
            "volume_ratio_20d": [2.0],
            "rs_line_eligibility": ["ELIGIBLE"],
            "rs_line_distance_from_high_pct": [0.0],
            "price_distance_from_high_pct": [5.0],
            "rs_rating": [90],
            "sma50": [105.0],
            "sma150": [95.0],
            "sma200": [90.0],
            "return_63d": [12.0],
            "previous_close": [105.0],
            "daily_close_position": [0.75],
            "distance_from_20d_high_pct": [2.0],
            "daily_range": [2.0],
            "median_range_20d": [2.5],
            "vcp_stars": [4],
            "pole_gain_pct": [15.0],
            "consolidation_sessions": [10],
            "consolidation_depth_pct": [12.0],
            "consolidation_volume_ratio": [0.8],
            "gap_pct": [4.0],
            "gap_and_hold": [True],
            "daily_inside_bar": [True],
            "double_inside_bar": [True],
            "weekly_inside_bar": [True],
        }
    )
    dry = base.copy()
    dry.loc[0, "symbol"] = "DRY"
    dry.loc[0, "volume_ratio_20d"] = 0.4
    down = base.copy()
    down.loc[0, "symbol"] = "DOWN"
    down.loc[0, "gap_pct"] = -4.0
    down.loc[0, "gap_and_hold"] = False
    return pd.concat([base, dry, down], ignore_index=True)


def matching_events():
    events = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "event_type": ["RESULTS_DUE", "RESULT_FILED"],
            "event_date": pd.to_datetime(["2026-08-20", "2026-08-12"]),
            "broadcast_at": [
                pd.NaT,
                pd.Timestamp("2026-08-12 18:30", tz="Asia/Kolkata"),
            ],
            "source_url": ["nse", "nse"],
        }
    )
    events.attrs["status"] = "COMPLETE"
    return events


def test_catalogue_contains_every_approved_preset_in_category_order():
    assert set(SCREENER_CATALOG) == EXPECTED
    categories = [definition.category for definition in SCREENER_CATALOG.values()]
    assert categories[0] == "Horizontal resistance"
    assert categories[-1] == "Inside bar"


def test_every_preset_can_produce_a_real_match():
    results = evaluate_all_screeners(matching_features(), matching_events())
    assert set(results["screener"]) == EXPECTED
    has_match = results.groupby("screener")["state"].apply(
        lambda states: states.eq("MATCH").any()
    )
    assert has_match.all()


def test_missing_required_feature_is_not_a_negative_result():
    features = pd.DataFrame({"symbol": ["IPO"], "history_sessions": [20]})
    result = evaluate_screener("vcp", features, pd.DataFrame(), {})
    assert result.iloc[0]["state"] == "NOT ELIGIBLE"


def test_adjustable_gap_threshold_changes_match():
    features = matching_features()
    assert evaluate_screener("gap_up", features, pd.DataFrame(), {}).iloc[0][
        "state"
    ] == "MATCH"
    assert evaluate_screener(
        "gap_up", features, pd.DataFrame(), {"minimum_gap_pct": 4.1}
    ).iloc[0]["state"] == "NO MATCH"
    assert default_thresholds("gap_up")["minimum_gap_pct"] == 3.0


def test_earnings_provider_failure_is_incomplete_not_no_match():
    events = matching_events().iloc[0:0]
    events.attrs["status"] = "SCAN INCOMPLETE"
    result = evaluate_screener("results_due", matching_features(), events, {})
    assert result.iloc[0]["state"] == "SCAN INCOMPLETE"


def test_benchmark_provider_failure_is_incomplete_not_no_match():
    features = matching_features()
    features["benchmark_status"] = "SCAN INCOMPLETE"
    result = evaluate_screener(
        "rs_high_before_price_high", features, matching_events(), {}
    )
    assert set(result["state"]) == {"SCAN INCOMPLETE"}


def test_multiple_scans_lists_reasons_and_count():
    matches = evaluate_all_screeners(matching_features(), matching_events())
    result = multiple_scan_matches(matches, ["nr7", "gap_up"], 2)
    assert result.iloc[0]["match_count"] == 2
    assert result.iloc[0]["matched_screeners"] == "NR7 | Gap up"
