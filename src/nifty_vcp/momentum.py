"""Cross-sectional weighted price momentum."""

from __future__ import annotations

import pandas as pd

from nifty_vcp.models import ScanConfig


def calculate_momentum(
    frame: pd.DataFrame, config: ScanConfig | None = None
) -> dict[str, float]:
    config = config or ScanConfig()
    required = max(config.momentum_sessions) + 1
    if len(frame) < required:
        raise ValueError(f"momentum requires {required} completed sessions")
    close = pd.to_numeric(frame["Close"], errors="raise").astype(float)
    latest = float(close.iloc[-1])
    result: dict[str, float] = {}
    weighted = 0.0
    for sessions, weight in zip(
        config.momentum_sessions, config.momentum_weights, strict=True
    ):
        value = latest / float(close.iloc[-1 - sessions]) - 1.0
        result[f"return_{sessions}d"] = value
        weighted += weight * value
    result["weighted_momentum"] = weighted
    return result


def rank_relative_strength(
    histories: dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    config: ScanConfig | None = None,
) -> pd.DataFrame:
    config = config or ScanConfig()
    metadata = universe.set_index("symbol")
    rows = []
    for symbol, frame in histories.items():
        values = calculate_momentum(frame, config)
        record = metadata.loc[symbol]
        rows.append(
            {
                "symbol": symbol,
                "company_name": record.get("company_name", ""),
                "industry": record.get("industry", ""),
                "yahoo_symbol": record.get("yahoo_symbol", f"{symbol}.NS"),
                "latest_close": float(frame["Close"].iloc[-1]),
                "price_date": pd.Timestamp(frame.index[-1]).date().isoformat(),
                **values,
            }
        )
    columns = [
        "symbol",
        "company_name",
        "industry",
        "yahoo_symbol",
        "latest_close",
        "price_date",
        *(f"return_{sessions}d" for sessions in config.momentum_sessions),
        "weighted_momentum",
        "rs_rating",
        "is_high_rs",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    result = pd.DataFrame(rows)
    count = len(result)
    if count == 1:
        result["rs_rating"] = 99
    else:
        average_rank = result["weighted_momentum"].rank(
            method="average", ascending=True
        )
        result["rs_rating"] = (
            1 + 98 * (average_rank - 1) / (count - 1)
        ).round().astype(int)
    result["is_high_rs"] = result["rs_rating"] >= config.high_rs_threshold
    return result.loc[:, columns].sort_values(
        ["rs_rating", "weighted_momentum", "symbol"],
        ascending=[False, False, True],
        ignore_index=True,
    )
