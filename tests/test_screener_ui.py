import pandas as pd
from streamlit.testing.v1 import AppTest

from screener_ui import filter_preset_results, selected_result_symbol


def test_all_reference_categories_render():
    at = AppTest.from_file("streamlit_screener_fixture.py").run()
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
    at = AppTest.from_file("streamlit_screener_fixture.py").run()
    at.button(key="screen_gap_screeners").click().run()
    assert not at.exception
    assert any(heading.value == "Gap screeners" for heading in at.header)
    at.number_input(key="threshold_gap_up_minimum_gap_pct").set_value(4.1).run()
    assert not at.exception


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
