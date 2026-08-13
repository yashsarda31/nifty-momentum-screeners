import json

import pandas as pd
import pytest

from nifty_vcp.custom_screeners import (
    CustomScreener,
    Rule,
    delete_screener,
    evaluate_custom,
    load_store,
    rename_screener,
    save_screener,
)


def test_custom_screener_round_trip_and_and_semantics(tmp_path):
    path = tmp_path / "custom_screeners.json"
    screener = CustomScreener(
        "Strong and liquid",
        (Rule("rs_rating", ">=", 80), Rule("volume_ratio_20d", ">=", 1.5)),
    )
    save_screener(path, screener)
    loaded = load_store(path)["Strong and liquid"]
    result = evaluate_custom(
        loaded,
        pd.DataFrame(
            {
                "symbol": ["PASS", "FAIL"],
                "rs_rating": [90, 90],
                "volume_ratio_20d": [2.0, 1.0],
            }
        ),
    )
    assert list(result.loc[result["state"] == "MATCH", "symbol"]) == ["PASS"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert list(tmp_path.iterdir()) == [path]


def test_unknown_field_survives_load_but_evaluates_ineligible(tmp_path):
    path = tmp_path / "custom_screeners.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "screeners": {
                    "Legacy": {
                        "rules": [
                            {"field": "retired_field", "operator": ">=", "value": 1}
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = load_store(path)["Legacy"]
    result = evaluate_custom(loaded, pd.DataFrame({"symbol": ["AAA"]}))
    assert result.iloc[0]["state"] == "NOT ELIGIBLE"
    assert "retired_field" in result.iloc[0]["reason"]


@pytest.mark.parametrize("operator", [">", ">=", "<", "<=", "==", "!="])
def test_all_supported_operators(operator):
    assert Rule("value", operator, 1).operator == operator


def test_invalid_rule_and_empty_screener_are_rejected():
    with pytest.raises(ValueError, match="operator"):
        Rule("rs_rating", "contains", 80)
    with pytest.raises(ValueError, match="name"):
        CustomScreener(" ", (Rule("rs_rating", ">=", 80),))
    with pytest.raises(ValueError, match="rule"):
        CustomScreener("Empty", ())
    with pytest.raises(ValueError, match="finite"):
        Rule("rs_rating", ">=", float("nan"))


def test_save_rename_collision_overwrite_and_delete(tmp_path):
    path = tmp_path / "custom_screeners.json"
    first = CustomScreener("First", (Rule("rs_rating", ">=", 80),))
    second = CustomScreener("Second", (Rule("industry", "==", "Banks"),))
    save_screener(path, first)
    save_screener(path, second)
    with pytest.raises(FileExistsError):
        save_screener(path, first)
    save_screener(path, first, overwrite=True)
    with pytest.raises(FileExistsError):
        rename_screener(path, "First", "Second")
    rename_screener(path, "First", "Renamed")
    assert set(load_store(path)) == {"Renamed", "Second"}
    delete_screener(path, "Second")
    assert set(load_store(path)) == {"Renamed"}


def test_numeric_and_string_rules_reject_missing_or_invalid_data():
    screener = CustomScreener(
        "Banks",
        (Rule("rs_rating", ">=", 80), Rule("industry", "==", "Banks")),
    )
    features = pd.DataFrame(
        {
            "symbol": ["GOOD", "BAD", "MISSING"],
            "rs_rating": [90, "not-a-number", None],
            "industry": ["Banks", "Banks", "Banks"],
        }
    )
    result = evaluate_custom(screener, features)
    assert list(result["state"]) == ["MATCH", "NOT ELIGIBLE", "NOT ELIGIBLE"]
