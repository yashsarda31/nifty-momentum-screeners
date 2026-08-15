import pandas as pd

from nifty_vcp.watchlist import (
    build_tradingview_watchlist,
    format_tradingview_watchlist,
)


def test_watchlist_keeps_liquid_complete_high_rs_names_and_caps_at_25():
    rows = []
    for index in range(30):
        rows.append(
            {
                "symbol": f"STOCK{index:02d}",
                "company_name": f"Stock {index}",
                "rs_rating": 99 - index,
                "vcp_stars": index % 6,
                "median_traded_value_60d": 100_000_000 + index,
                "top_1000_liquid": True,
                "is_high_rs": True,
                "history_status": "COMPLETE",
            }
        )
    rows.extend(
        [
            {
                "symbol": "ILLIQUID",
                "rs_rating": 99,
                "vcp_stars": 5,
                "median_traded_value_60d": 99_999_999,
                "top_1000_liquid": True,
                "is_high_rs": True,
                "history_status": "COMPLETE",
            },
            {
                "symbol": "IPOONLY",
                "rs_rating": 99,
                "vcp_stars": 5,
                "median_traded_value_60d": 200_000_000,
                "top_1000_liquid": False,
                "is_high_rs": True,
                "history_status": "COMPLETE",
            },
            {
                "symbol": "INCOMPLETE",
                "rs_rating": 99,
                "vcp_stars": 5,
                "median_traded_value_60d": 200_000_000,
                "top_1000_liquid": True,
                "is_high_rs": True,
                "history_status": "SCAN INCOMPLETE",
            },
        ]
    )

    result = build_tradingview_watchlist(pd.DataFrame(rows))

    assert len(result) == 25
    assert result.iloc[0]["symbol"] == "STOCK00"
    assert result.iloc[-1]["symbol"] == "STOCK24"
    assert {"ILLIQUID", "IPOONLY", "INCOMPLETE"}.isdisjoint(result["symbol"])
    assert result["tradingview_symbol"].iloc[0] == "NSE:STOCK00"


def test_watchlist_uses_vcp_then_liquidity_as_rs_tiebreakers():
    features = pd.DataFrame(
        {
            "symbol": ["LOWVCP", "LOWLIQ", "WINNER"],
            "rs_rating": [95, 95, 95],
            "vcp_stars": [3, 5, 5],
            "median_traded_value_60d": [500_000_000, 150_000_000, 250_000_000],
            "top_1000_liquid": [True, True, True],
            "is_high_rs": [True, True, True],
            "history_status": ["COMPLETE", "COMPLETE", "COMPLETE"],
        }
    )

    result = build_tradingview_watchlist(features)

    assert result["symbol"].tolist() == ["WINNER", "LOWLIQ", "LOWVCP"]


def test_tradingview_watchlist_is_copyable_comma_separated_nse_symbols():
    watchlist = pd.DataFrame(
        {"tradingview_symbol": ["NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK"]}
    )

    assert format_tradingview_watchlist(watchlist) == (
        "NSE:RELIANCE,NSE:TCS,NSE:HDFCBANK"
    )


def test_watchlist_uses_selected_universe_when_feature_liquidity_is_blank():
    features = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "rs_rating": [99],
            "vcp_stars": [5],
            "median_traded_value_60d": [None],
            "top_1000_liquid": [True],
            "is_high_rs": [True],
            "history_status": ["COMPLETE"],
        }
    )
    selected_universe = pd.DataFrame(
        {"symbol": ["AAA"], "median_traded_value_60d": [150_000_000]}
    )

    result = build_tradingview_watchlist(features, selected_universe)

    assert result["symbol"].tolist() == ["AAA"]
    assert result.iloc[0]["median_traded_value_60d"] == 150_000_000
