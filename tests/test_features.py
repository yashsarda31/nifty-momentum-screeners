import numpy as np
import pandas as pd
import pytest

from nifty_vcp.features import build_feature_matrix, history_evidence


def price_frame(
    periods=280,
    *,
    start=100.0,
    end=150.0,
    volume=1_000_000.0,
    end_date="2026-08-07",
):
    index = pd.bdate_range(end=end_date, periods=periods)
    close = np.linspace(start, end, periods)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(periods, volume),
        },
        index=index,
    )


def universe(symbol="AAA", listing_date="2000-01-01"):
    return pd.DataFrame(
        {
            "symbol": [symbol],
            "company_name": [f"{symbol} Limited"],
            "industry": ["Test"],
            "series": ["EQ"],
            "isin": ["INE000A01001"],
            "listing_date": pd.to_datetime([listing_date]),
            "yahoo_symbol": [f"{symbol}.NS"],
            "liquidity_rank": pd.array([1], dtype="Int64"),
            "top_1000_liquid": [True],
            "recent_ipo_overlay": [listing_date >= "2024-08-13"],
        }
    )


def benchmark(periods=280):
    return price_frame(periods, start=100, end=110)


def build_one(frame, *, symbol="AAA", listing_date="2000-01-01"):
    return build_feature_matrix(
        {symbol: frame},
        universe(symbol, listing_date),
        benchmark(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.Timestamp("2026-08-13"),
    ).iloc[0]


def test_short_ipo_can_break_out_without_long_history():
    frame = price_frame(25, start=100, end=108)
    frame.iloc[-1, frame.columns.get_loc("Close")] = frame["High"].iloc[-21:-1].max() + 1
    frame.iloc[-1, frame.columns.get_loc("High")] = frame["Close"].iloc[-1] + 1
    frame.iloc[-1, frame.columns.get_loc("Volume")] = 2_000_000

    row = build_one(frame, symbol="IPO", listing_date="2026-07-01")

    assert row["history_sessions"] == 25
    assert bool(row["ipo_breakout"])
    assert pd.isna(row["return_252d"])
    assert row["momentum_eligibility"] == "NOT ELIGIBLE"


def test_tight_gap_volume_and_inside_bar_features_are_auditable():
    frame = price_frame(30, start=100, end=110)
    prior_close = frame["Close"].iloc[-2]
    frame.iloc[-1, frame.columns.get_loc("Open")] = prior_close * 1.03
    frame.iloc[-1, frame.columns.get_loc("Close")] = prior_close * 1.04
    frame.iloc[-1, frame.columns.get_loc("High")] = frame["High"].iloc[-2] - 0.1
    frame.iloc[-1, frame.columns.get_loc("Low")] = frame["Low"].iloc[-2] + 0.1
    frame.iloc[-1, frame.columns.get_loc("Volume")] = 2_000_000

    row = build_one(frame)

    assert row["gap_pct"] == pytest.approx(3.0)
    assert row["previous_close"] == pytest.approx(prior_close)
    assert row["scan_date"] == "2026-08-13"
    assert row["prior_20_high"] == pytest.approx(frame["High"].iloc[-21:-1].max())
    assert row["daily_close_position"] >= 0.5
    assert bool(row["daily_inside_bar"])
    assert row["volume_ratio_20d"] > 1.5
    assert row["three_close_band_pct"] >= 0
    assert isinstance(row["nr7"], (bool, np.bool_))


def test_horizontal_resistance_uses_confirmed_swing_high_touches():
    frame = price_frame(80, start=90, end=98)
    for position, high in ((-50, 100.0), (-30, 100.8), (-10, 99.7)):
        frame.iloc[position, frame.columns.get_loc("High")] = high
        for offset in (-2, -1, 1, 2):
            frame.iloc[position + offset, frame.columns.get_loc("High")] = high - 3
    frame.iloc[-1, frame.columns.get_loc("Close")] = 97.0

    row = build_one(frame)

    assert row["resistance_touches"] >= 3
    assert row["resistance_dispersion_pct"] <= 2.0
    assert bool(row["horizontal_resistance"])


def test_rs_line_can_hit_high_before_stock_price():
    stock = price_frame(280, start=100, end=130)
    stock.iloc[-40, stock.columns.get_loc("High")] = 160.0
    bench = benchmark()
    bench.loc[:, "Close"] = np.linspace(100, 80, len(bench))

    row = build_feature_matrix(
        {"RS": stock},
        universe("RS"),
        bench,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.Timestamp("2026-08-13"),
    ).iloc[0]

    assert row["rs_line_eligibility"] == "ELIGIBLE"
    assert bool(row["rs_high_before_price_high"])
    assert row["price_distance_from_high_pct"] > 0


def test_double_and_weekly_inside_bars_are_detected():
    frame = price_frame(40, end_date="2026-08-07")
    frame.iloc[-2, frame.columns.get_loc("High")] = frame["High"].iloc[-3] - 0.2
    frame.iloc[-2, frame.columns.get_loc("Low")] = frame["Low"].iloc[-3] + 0.2
    frame.iloc[-1, frame.columns.get_loc("High")] = frame["High"].iloc[-2] - 0.2
    frame.iloc[-1, frame.columns.get_loc("Low")] = frame["Low"].iloc[-2] + 0.2
    prior_week = frame.loc["2026-07-27":"2026-07-31"]
    latest_week = frame.loc["2026-08-03":"2026-08-07"]
    frame.loc[latest_week.index, "High"] = prior_week["High"].max() - 0.5
    frame.loc[latest_week.index, "Low"] = prior_week["Low"].min() + 0.5

    row = build_one(frame)

    assert bool(row["double_inside_bar"])
    assert bool(row["weekly_inside_bar"])


def test_rankings_and_vcp_evidence_are_merged_by_symbol():
    frame = price_frame()
    result = build_feature_matrix(
        {"AAA": frame},
        universe(),
        benchmark(),
        pd.DataFrame({"symbol": ["AAA"], "rs_rating": [91]}),
        pd.DataFrame({"symbol": ["AAA"], "vcp_stars": [4]}),
        pd.Timestamp("2026-08-13"),
    )
    assert result.iloc[0]["rs_rating"] == 91
    assert result.iloc[0]["vcp_stars"] == 4


def test_history_evidence_has_stable_symbol_date_and_ohlcv_schema():
    frame = price_frame(15)
    evidence = history_evidence({"AAA": frame})
    assert list(evidence.columns) == [
        "symbol",
        "date",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "week_ending",
    ]
    assert len(evidence) == 15
