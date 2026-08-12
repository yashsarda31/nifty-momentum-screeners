import tomllib
from pathlib import Path

import pytest

from nifty_vcp.models import ScanConfig


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


def test_runtime_dependencies_include_scipy_for_yfinance_repair():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    assert any(dependency.startswith("scipy") for dependency in dependencies)
