"""Transparent, Minervini-inspired five-star VCP scoring."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nifty_vcp.models import ScanConfig, VCPResult

COMPONENT_NAMES = (
    "trend_template",
    "range_position",
    "contracting_ranges",
    "contracting_volatility",
    "pivot_readiness",
)


def _normalized_range(frame: pd.DataFrame, sessions: int) -> float:
    window = frame.tail(sessions)
    high = float(window["High"].max())
    low = float(window["Low"].min())
    return (high - low) / low


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["Close"].shift(1)
    return pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - previous_close).abs(),
            (frame["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def score_vcp(frame: pd.DataFrame, pivot_sessions: int = 55) -> VCPResult:
    if len(frame) < 273:
        raise ValueError("VCP scoring requires at least 273 completed sessions")
    close_series = pd.to_numeric(frame["Close"], errors="raise").astype(float)
    close = float(close_series.iloc[-1])
    sma50 = float(close_series.tail(50).mean())
    sma150 = float(close_series.tail(150).mean())
    sma200 = float(close_series.tail(200).mean())
    sma200_20d_ago = float(close_series.iloc[:-20].tail(200).mean())
    trend_template = (
        close > sma50 > sma150 > sma200 > sma200_20d_ago
    )

    annual = frame.tail(252)
    high_252 = float(annual["High"].max())
    low_252 = float(annual["Low"].min())
    pct_below_high = (1.0 - close / high_252) * 100.0
    pct_above_low = (close / low_252 - 1.0) * 100.0
    range_position = close >= 0.85 * high_252 and close >= 1.30 * low_252

    range_60 = _normalized_range(frame, 60)
    range_30 = _normalized_range(frame, 30)
    range_15 = _normalized_range(frame, 15)
    contracting_ranges = (
        range_60 > range_30 > range_15 and range_15 <= 0.60 * range_60
    )

    true_range = _true_range(frame)
    atr_50 = float(true_range.tail(50).mean() / close)
    atr_20 = float(true_range.tail(20).mean() / close)
    atr_10 = float(true_range.tail(10).mean() / close)
    contracting_volatility = atr_10 < atr_20 < atr_50

    pivot = float(frame["High"].tail(pivot_sessions).max())
    distance = (pivot - close) / pivot * 100.0
    avg_volume_10 = float(frame["Volume"].tail(10).mean())
    avg_volume_50 = float(frame["Volume"].tail(50).mean())
    volume_ratio = avg_volume_10 / avg_volume_50 if avg_volume_50 > 0 else np.inf
    tolerance = 1e-9
    pivot_readiness = distance <= 5.0 + tolerance and volume_ratio <= 0.75 + tolerance

    components = {
        "trend_template": bool(trend_template),
        "range_position": bool(range_position),
        "contracting_ranges": bool(contracting_ranges),
        "contracting_volatility": bool(contracting_volatility),
        "pivot_readiness": bool(pivot_readiness),
    }
    evidence = {
        "close": close,
        "sma50": sma50,
        "sma150": sma150,
        "sma200": sma200,
        "sma200_20d_ago": sma200_20d_ago,
        "high_252": high_252,
        "low_252": low_252,
        "pct_below_high": pct_below_high,
        "pct_above_low": pct_above_low,
        "range_60_pct": range_60 * 100.0,
        "range_30_pct": range_30 * 100.0,
        "range_15_pct": range_15 * 100.0,
        "atr_50_pct": atr_50 * 100.0,
        "atr_20_pct": atr_20 * 100.0,
        "atr_10_pct": atr_10 * 100.0,
        "pivot_55": pivot,
        "distance_to_pivot_pct": distance,
        "avg_volume_10": avg_volume_10,
        "avg_volume_50": avg_volume_50,
        "volume_ratio": volume_ratio,
    }
    return VCPResult(sum(components.values()), components, evidence)


def score_high_rs(
    histories: dict[str, pd.DataFrame],
    rankings: pd.DataFrame,
    config: ScanConfig | None = None,
) -> pd.DataFrame:
    config = config or ScanConfig()
    rows = []
    for ranking in rankings.loc[rankings["is_high_rs"]].to_dict("records"):
        symbol = ranking["symbol"]
        result = score_vcp(histories[symbol], config.pivot_sessions)
        row = dict(ranking)
        row["vcp_stars"] = result.total_stars
        row.update({f"vcp_{name}": passed for name, passed in result.components.items()})
        row.update(result.evidence)
        rows.append(row)
    if not rows:
        return pd.DataFrame(
            columns=[*rankings.columns, "vcp_stars", *(f"vcp_{n}" for n in COMPONENT_NAMES)]
        )
    return pd.DataFrame(rows).sort_values(
        ["vcp_stars", "rs_rating", "symbol"],
        ascending=[False, False, True],
        ignore_index=True,
    )
