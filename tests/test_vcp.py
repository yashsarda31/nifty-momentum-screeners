import numpy as np
import pandas as pd

from nifty_vcp.models import ScanConfig
from nifty_vcp.vcp import score_high_rs, score_vcp


def vcp_frame():
    periods = 320
    close = np.linspace(50.0, 100.0, periods)
    width = np.full(periods, 0.025)
    width[-50:] = 0.020
    width[-20:] = 0.010
    width[-10:] = 0.003
    volume = np.full(periods, 1_000_000.0)
    volume[-10:] = 500_000.0
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * (1 + width),
            "Low": close * (1 - width),
            "Close": close,
            "Volume": volume,
        },
        index=pd.bdate_range("2025-01-01", periods=periods),
    )


def test_constructive_vcp_earns_all_five_stars_and_evidence():
    result = score_vcp(vcp_frame())
    assert result.total_stars == 5
    assert all(result.components.values())
    assert result.total_stars == sum(result.components.values())
    assert {
        "close",
        "sma50",
        "sma150",
        "sma200",
        "sma200_20d_ago",
        "high_252",
        "low_252",
        "pct_below_high",
        "pct_above_low",
        "range_60_pct",
        "range_30_pct",
        "range_15_pct",
        "atr_50_pct",
        "atr_20_pct",
        "atr_10_pct",
        "pivot_55",
        "distance_to_pivot_pct",
        "avg_volume_10",
        "avg_volume_50",
        "volume_ratio",
    } <= set(result.evidence)


def test_each_component_can_fail_and_total_matches_components():
    base = vcp_frame()
    cases = {}

    trend = base.copy()
    trend.loc[trend.index[-1], "Close"] = 40.0
    trend.loc[trend.index[-1], ["Open", "Low"]] = 39.0
    trend.loc[trend.index[-1], "High"] = 41.0
    cases["trend_template"] = trend

    position = base.copy()
    position.loc[position.index[-200], "High"] = 200.0
    cases["range_position"] = position

    ranges = base.copy()
    ranges.loc[ranges.index[-5], "High"] = 130.0
    cases["contracting_ranges"] = ranges

    volatility = base.copy()
    volatility.loc[volatility.index[-10]:, "High"] *= 1.08
    volatility.loc[volatility.index[-10]:, "Low"] *= 0.92
    cases["contracting_volatility"] = volatility

    pivot = base.copy()
    pivot.loc[pivot.index[-55], "High"] = 130.0
    pivot.loc[pivot.index[-10]:, "Volume"] = 1_000_000.0
    cases["pivot_readiness"] = pivot

    for component, frame in cases.items():
        result = score_vcp(frame)
        assert not result.components[component]
        assert result.total_stars == sum(result.components.values())


def test_pivot_readiness_boundaries_are_inclusive():
    frame = vcp_frame()
    latest_close = float(frame["Close"].iloc[-1])
    pivot = latest_close / 0.95
    frame.loc[frame.index[-55], "High"] = pivot
    frame.loc[frame.index[-10]:, "Volume"] = 750_000.0
    frame.loc[frame.index[-50:-10], "Volume"] = 1_062_500.0
    result = score_vcp(frame)
    assert result.evidence["distance_to_pivot_pct"] <= 5.0 + 1e-9
    assert result.evidence["volume_ratio"] <= 0.75 + 1e-9
    assert result.components["pivot_readiness"]

    frame.loc[frame.index[-10]:, "Volume"] += 1_000.0
    assert not score_vcp(frame).components["pivot_readiness"]


def test_score_high_rs_excludes_lower_ranked_stocks():
    rankings = pd.DataFrame(
        {
            "symbol": ["HIGH", "LOW"],
            "company_name": ["High", "Low"],
            "rs_rating": [95, 79],
            "is_high_rs": [True, False],
        }
    )
    result = score_high_rs(
        {"HIGH": vcp_frame(), "LOW": vcp_frame()}, rankings, ScanConfig()
    )
    assert list(result["symbol"]) == ["HIGH"]
    assert result.iloc[0]["vcp_stars"] == 5
