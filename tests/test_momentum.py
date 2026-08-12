import numpy as np
import pandas as pd
import pytest

from nifty_vcp.models import ScanConfig
from nifty_vcp.momentum import calculate_momentum, rank_relative_strength


def frame_from_close(close):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {"Close": close}, index=pd.bdate_range("2025-01-01", periods=len(close))
    )


def test_calculate_momentum_uses_trading_session_offsets_and_weights():
    close = np.linspace(100.0, 200.0, 300)
    result = calculate_momentum(frame_from_close(close), ScanConfig())
    expected = {
        sessions: close[-1] / close[-1 - sessions] - 1
        for sessions in (63, 126, 189, 252)
    }
    for sessions, value in expected.items():
        assert result[f"return_{sessions}d"] == pytest.approx(value)
    assert result["weighted_momentum"] == pytest.approx(
        0.4 * expected[63]
        + 0.2 * expected[126]
        + 0.2 * expected[189]
        + 0.2 * expected[252]
    )


def test_calculate_momentum_rejects_insufficient_history():
    with pytest.raises(ValueError, match="253 completed sessions"):
        calculate_momentum(frame_from_close(np.arange(252) + 100), ScanConfig())


def test_rs_rank_is_bounded_tie_aware_and_input_order_independent():
    universe = pd.DataFrame(
        {
            "symbol": ["WEAK", "TIE1", "TIE2", "LEAD"],
            "company_name": ["Weak", "Tie One", "Tie Two", "Leader"],
            "industry": ["A", "B", "B", "C"],
            "yahoo_symbol": ["WEAK.NS", "TIE1.NS", "TIE2.NS", "LEAD.NS"],
        }
    )
    histories = {
        "LEAD": frame_from_close(np.geomspace(100, 300, 300)),
        "TIE2": frame_from_close(np.geomspace(100, 180, 300)),
        "WEAK": frame_from_close(np.geomspace(100, 110, 300)),
        "TIE1": frame_from_close(np.geomspace(100, 180, 300)),
    }
    ranked = rank_relative_strength(histories, universe, ScanConfig())
    ratings = ranked.set_index("symbol")["rs_rating"]
    assert ratings["LEAD"] == 99
    assert ratings["WEAK"] == 1
    assert ratings["TIE1"] == ratings["TIE2"]
    assert ranked["rs_rating"].between(1, 99).all()
    assert ranked.iloc[0]["symbol"] == "LEAD"
    assert bool(ranked.iloc[0]["is_high_rs"])


def test_single_valid_stock_receives_99():
    universe = pd.DataFrame(
        {
            "symbol": ["ONLY"],
            "company_name": ["Only"],
            "industry": ["A"],
            "yahoo_symbol": ["ONLY.NS"],
        }
    )
    ranked = rank_relative_strength(
        {"ONLY": frame_from_close(np.geomspace(100, 150, 300))},
        universe,
        ScanConfig(),
    )
    assert ranked.iloc[0]["rs_rating"] == 99
