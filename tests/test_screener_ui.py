from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from screener_ui import (
    filter_preset_results,
    filter_result_view,
    result_display_columns,
    selected_result_symbol,
)


def test_result_view_defaults_to_matches_and_searches_symbol_or_company():
    results = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "company_name": ["Alpha Ltd", "Beta Industries", "Gamma Ltd"],
            "state": ["MATCH", "MATCH", "SCAN INCOMPLETE"],
        }
    )

    assert filter_result_view(results, "", "MATCH")["symbol"].tolist() == [
        "AAA",
        "BBB",
    ]
    assert filter_result_view(results, "beta", "MATCH")["symbol"].tolist() == [
        "BBB"
    ]
    assert filter_result_view(results, "CCC", "All states")["symbol"].tolist() == [
        "CCC"
    ]


def test_result_view_handles_missing_company_and_empty_results():
    results = pd.DataFrame({"symbol": ["AAA"], "state": ["NOT ELIGIBLE"]})

    assert filter_result_view(results, "", "MATCH").empty
    assert filter_result_view(results.iloc[0:0], "", "All states").empty


def test_all_reference_categories_render():
    at = AppTest.from_file(
        Path(__file__).parent / "streamlit_screener_fixture.py"
    ).run()
    assert not at.exception
    labels = {button.label for button in at.button}
    assert {
        "Create/load screener",
        "Multiple scans",
        "Horizontal resistance",
        "Tight setup",
        "IPO scanner",
        "RS high before price high",
        "Momentum scanner",
        "Volume screeners",
        "VCP",
        "Flags & pennants",
        "Earnings screeners",
        "Gap screeners",
        "Inside bar",
    } <= labels


def test_gap_category_threshold_controls_are_interactive():
    at = AppTest.from_file(
        Path(__file__).parent / "streamlit_screener_fixture.py"
    ).run()
    at.button(key="screen_gap_screeners").click().run()
    assert not at.exception
    assert any(heading.value == "Gap screeners" for heading in at.header)
    at.number_input(key="threshold_gap_up_minimum_gap_pct").set_value(4.1).run()
    assert not at.exception


def test_rendered_screener_table_shows_startup_quote_fields():
    at = AppTest.from_file(
        Path(__file__).parent / "streamlit_screener_fixture.py"
    ).run()
    at.button(key="screen_gap_screeners").click().run()

    assert not at.exception
    rendered = at.dataframe[0].value
    assert rendered.iloc[0]["latest_price"] == 105.0
    assert rendered.iloc[0]["price_change_pct"] == 5.0
    assert rendered.iloc[0]["quote_status"] == "LIVE"


def test_screener_workspace_exports_current_screen_matches_not_top_25():
    at = AppTest.from_file(
        Path(__file__).parent / "streamlit_screener_fixture.py"
    ).run()
    at.button(key="screen_gap_screeners").click().run()

    assert not at.exception
    assert any(
        subheader.value == "Export screen results to TradingView"
        for subheader in at.subheader
    )
    assert any(code.value == "NSE:AAA" for code in at.code)
    assert all("TOP25ONLY" not in code.value for code in at.code)
    assert any(
        element.label == "Download screen results"
        for element in at.get("download_button")
    )


def test_screener_workspace_filters_visible_rows_before_export():
    at = AppTest.from_file(
        Path(__file__).parent / "streamlit_screener_fixture.py"
    ).run()
    at.button(key="screen_gap_screeners").click().run()

    assert at.selectbox(key="screener_result_state").value == "MATCH"
    assert at.dataframe[0].value["symbol"].tolist() == ["AAA"]

    at.selectbox(key="screener_result_state").select("All states").run()
    at.text_input(key="screener_result_search").set_value("TOP25").run()

    assert not at.exception
    assert at.dataframe[0].value["symbol"].tolist() == ["TOP25ONLY"]
    assert all("TOP25ONLY" not in item.value for item in at.code)


def test_multiple_scan_results_survive_filter_widget_reruns():
    at = AppTest.from_file(
        Path(__file__).parent / "streamlit_screener_fixture.py"
    ).run()
    at.button(key="screen_multiple_scans").click().run()
    at.multiselect(key="multiple_presets").set_value(["Gap up"]).run()
    at.number_input(key="minimum_matches").set_value(1).run()
    next(
        button for button in at.button if button.label == "Run multiple scans"
    ).click().run()

    assert at.selectbox(key="screener_result_state").value == "MATCH"
    at.text_input(key="screener_result_search").set_value("AAA").run()

    assert not at.exception
    assert at.selectbox(key="screener_result_state").value == "MATCH"
    assert at.dataframe[0].value["symbol"].tolist() == ["AAA"]


def test_threshold_filter_recalculates_from_stored_features():
    features = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "company_name": ["AAA"],
            "price_date": ["2026-08-13"],
            "gap_pct": [4.0],
        }
    )
    loose = filter_preset_results("gap_up", features, pd.DataFrame(), {})
    strict = filter_preset_results(
        "gap_up", features, pd.DataFrame(), {"minimum_gap_pct": 4.1}
    )
    assert loose.iloc[0]["state"] == "MATCH"
    assert strict.iloc[0]["state"] == "NO MATCH"


def test_selected_result_symbol_handles_streamlit_event_shape():
    frame = pd.DataFrame({"symbol": ["AAA", "BBB"]})
    assert selected_result_symbol({"selection": {"rows": [1]}}, frame) == "BBB"
    assert selected_result_symbol({"selection": {"rows": []}}, frame) is None


def test_result_display_columns_include_startup_prices_when_present():
    results = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "price_date": ["2026-08-13"],
            "latest_price": [105.0],
            "price_change_pct": [5.0],
            "quote_status": ["LIVE"],
            "quote_timestamp": ["2026-08-14T10:00:00+05:30"],
            "state": ["MATCH"],
        }
    )

    assert result_display_columns(results) == [
        "symbol",
        "state",
        "latest_price",
        "quote_timestamp",
        "quote_status",
        "price_change_pct",
        "price_date",
    ]
