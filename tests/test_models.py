import tomllib
from pathlib import Path

import pytest

from nifty_vcp.models import ScanConfig, ScreenerState


def test_scan_config_rejects_invalid_thresholds():
    with pytest.raises(ValueError, match="coverage_threshold"):
        ScanConfig(coverage_threshold=1.1)
    with pytest.raises(ValueError, match="high_rs_threshold"):
        ScanConfig(high_rs_threshold=100)


def test_scan_config_defaults_match_approved_design():
    config = ScanConfig()
    assert config.high_rs_threshold == 80
    assert config.pivot_sessions == 55
    assert config.coverage_threshold == 0.90
    assert config.momentum_sessions == (63, 126, 189, 252)
    assert config.momentum_weights == (0.40, 0.20, 0.20, 0.20)


def test_expanded_scan_defaults_and_states():
    config = ScanConfig()
    assert config.liquidity_count == 1_000
    assert config.liquidity_sessions == 60
    assert config.liquidity_min_observations == 40
    assert config.recent_ipo_days == 730
    assert config.minimum_history_sessions == 15
    assert {state.value for state in ScreenerState} == {
        "MATCH",
        "NO MATCH",
        "NOT ELIGIBLE",
        "SCAN INCOMPLETE",
    }


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"liquidity_count": 0}, "liquidity_count"),
        ({"liquidity_sessions": 0}, "liquidity_sessions"),
        ({"liquidity_min_observations": 61}, "liquidity_min_observations"),
        ({"recent_ipo_days": 0}, "recent_ipo_days"),
        ({"minimum_history_sessions": 14}, "minimum_history_sessions"),
    ],
)
def test_expanded_scan_config_rejects_invalid_values(kwargs, message):
    with pytest.raises(ValueError, match=message):
        ScanConfig(**kwargs)


def test_runtime_dependencies_include_scipy_for_yfinance_repair():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    assert any(dependency.startswith("scipy") for dependency in dependencies)
