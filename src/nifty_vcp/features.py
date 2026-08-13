"""Reusable, auditable daily feature calculations for named screeners."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


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


def _return(close: pd.Series, sessions: int) -> float:
    if len(close) <= sessions:
        return np.nan
    return (float(close.iloc[-1]) / float(close.iloc[-1 - sessions]) - 1.0) * 100.0


def _swing_resistance(frame: pd.DataFrame, sessions: int = 60) -> dict:
    window = frame.tail(sessions)
    high = window["High"].astype(float)
    pivots: list[float] = []
    for index in range(2, len(high) - 2):
        value = float(high.iloc[index])
        neighbours = pd.concat(
            [high.iloc[index - 2 : index], high.iloc[index + 1 : index + 3]]
        )
        if value > float(neighbours.max()):
            pivots.append(value)
    best: list[float] = []
    ordered = sorted(pivots)
    for start in range(len(ordered)):
        for stop in range(start + 1, len(ordered) + 1):
            cluster = ordered[start:stop]
            median = float(np.median(cluster))
            dispersion = (cluster[-1] - cluster[0]) / median * 100.0
            if dispersion > 2.0:
                break
            if len(cluster) > len(best) or (
                len(cluster) == len(best) and median > float(np.median(best))
            ):
                best = cluster
    if not best:
        return {
            "resistance_price": np.nan,
            "resistance_touches": 0,
            "resistance_dispersion_pct": np.nan,
            "distance_to_resistance_pct": np.nan,
            "horizontal_resistance": False,
        }
    resistance = float(np.median(best))
    dispersion = (max(best) - min(best)) / resistance * 100.0
    distance = (resistance - float(frame["Close"].iloc[-1])) / resistance * 100.0
    return {
        "resistance_price": resistance,
        "resistance_touches": len(best),
        "resistance_dispersion_pct": dispersion,
        "distance_to_resistance_pct": distance,
        "horizontal_resistance": bool(
            len(best) >= 3 and dispersion <= 2.0 and -2.0 <= distance <= 5.0
        ),
    }


def _weekly_inside(frame: pd.DataFrame) -> bool | pd.NA:
    data = frame.sort_index()
    if data.empty:
        return pd.NA
    week_end = data.index.to_period("W-FRI").end_time.normalize()
    completed = data.assign(_week_end=week_end)
    latest_date = pd.Timestamp(data.index[-1]).normalize()
    completed = completed[completed["_week_end"] <= latest_date]
    weekly = completed.groupby("_week_end").agg(High=("High", "max"), Low=("Low", "min"))
    if len(weekly) < 2:
        return pd.NA
    return bool(
        weekly["High"].iloc[-1] <= weekly["High"].iloc[-2]
        and weekly["Low"].iloc[-1] >= weekly["Low"].iloc[-2]
    )


def _flag_pennant(frame: pd.DataFrame) -> dict:
    best: dict | None = None
    for consolidation_sessions in range(5, 21):
        for pole_sessions in range(10, 31):
            required = consolidation_sessions + pole_sessions
            if len(frame) < required + 1:
                continue
            pole = frame.iloc[-required : -consolidation_sessions]
            consolidation = frame.iloc[-consolidation_sessions:]
            pole_start = float(pole["Close"].iloc[0])
            pole_gain = (float(pole["Close"].iloc[-1]) / pole_start - 1.0) * 100.0
            consolidation_high = float(consolidation["High"].max())
            depth = (
                (consolidation_high - float(consolidation["Low"].min()))
                / consolidation_high
                * 100.0
            )
            pole_volume = float(pole["Volume"].mean())
            volume_ratio = (
                float(consolidation["Volume"].mean()) / pole_volume
                if pole_volume > 0
                else np.nan
            )
            candidate = {
                "pole_gain_pct": pole_gain,
                "consolidation_sessions": consolidation_sessions,
                "consolidation_depth_pct": depth,
                "consolidation_volume_ratio": volume_ratio,
                "flags_pennants": bool(
                    pole_gain >= 15.0 and depth <= 12.0 and volume_ratio < 1.0
                ),
            }
            if best is None or (
                candidate["flags_pennants"], candidate["pole_gain_pct"]
            ) > (best["flags_pennants"], best["pole_gain_pct"]):
                best = candidate
    return best or {
        "pole_gain_pct": np.nan,
        "consolidation_sessions": pd.NA,
        "consolidation_depth_pct": np.nan,
        "consolidation_volume_ratio": np.nan,
        "flags_pennants": False,
    }


def _rs_line_features(frame: pd.DataFrame, benchmark: pd.DataFrame) -> dict:
    aligned = pd.concat(
        [frame["Close"].rename("stock"), benchmark["Close"].rename("benchmark")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 253:
        return {
            "rs_line_eligibility": "NOT ELIGIBLE",
            "rs_line_distance_from_high_pct": np.nan,
            "price_distance_from_high_pct": np.nan,
            "rs_high_before_price_high": pd.NA,
        }
    window = aligned.tail(252)
    ratio = window["stock"] / window["benchmark"]
    ratio_high = float(ratio.max())
    ratio_distance = (ratio_high - float(ratio.iloc[-1])) / ratio_high * 100.0
    price_high = float(frame["High"].tail(252).max())
    price_distance = (
        (price_high - float(frame["Close"].iloc[-1])) / price_high * 100.0
    )
    return {
        "rs_line_eligibility": "ELIGIBLE",
        "rs_line_distance_from_high_pct": ratio_distance,
        "price_distance_from_high_pct": price_distance,
        "rs_high_before_price_high": bool(
            ratio_distance <= 1e-9 and price_distance > 1e-9
        ),
    }


def _one_symbol_features(
    symbol: str,
    frame: pd.DataFrame,
    metadata: pd.Series,
    benchmark: pd.DataFrame,
    as_of: pd.Timestamp,
) -> dict:
    data = frame.sort_index().astype(float)
    close = data["Close"]
    ranges = data["High"] - data["Low"]
    latest_close = float(close.iloc[-1])
    listing_date = pd.Timestamp(metadata["listing_date"])
    as_of_date = pd.Timestamp(as_of)
    if as_of_date.tzinfo is not None:
        as_of_date = as_of_date.tz_localize(None)
    ipo_age_days = (as_of_date.normalize() - listing_date.normalize()).days

    averages = {
        sessions: float(close.tail(sessions).mean()) if len(close) >= sessions else np.nan
        for sessions in (20, 50, 150, 200)
    }
    previous_volume = data["Volume"].iloc[-21:-1]
    average_volume_20 = (
        float(previous_volume.mean()) if len(previous_volume) >= 20 else np.nan
    )
    volume_ratio = (
        float(data["Volume"].iloc[-1]) / average_volume_20
        if average_volume_20 > 0
        else np.nan
    )
    true_range = _true_range(data)
    atr14_pct = true_range.rolling(14).mean() / close * 100.0
    atr_average_50 = float(atr14_pct.tail(50).mean()) if len(data) >= 50 else np.nan
    current_atr = float(atr14_pct.iloc[-1]) if len(data) >= 14 else np.nan
    high_20 = float(data["High"].tail(20).max()) if len(data) >= 20 else np.nan
    close_distance_20 = (
        (high_20 - latest_close) / high_20 * 100.0 if np.isfinite(high_20) else np.nan
    )
    range_median_20 = float(ranges.tail(20).median()) if len(data) >= 20 else np.nan
    last_range = float(ranges.iloc[-1])
    daily_position = (
        (latest_close - float(data["Low"].iloc[-1])) / last_range
        if last_range > 0
        else np.nan
    )
    gap_pct = (
        (float(data["Open"].iloc[-1]) / float(close.iloc[-2]) - 1.0) * 100.0
        if len(data) >= 2
        else np.nan
    )
    daily_inside = bool(
        len(data) >= 2
        and data["High"].iloc[-1] <= data["High"].iloc[-2]
        and data["Low"].iloc[-1] >= data["Low"].iloc[-2]
    )
    double_inside = bool(
        len(data) >= 3
        and daily_inside
        and data["High"].iloc[-2] <= data["High"].iloc[-3]
        and data["Low"].iloc[-2] >= data["Low"].iloc[-3]
    )
    ipo_window = data.tail(min(60, len(data)))
    ipo_high = float(ipo_window["High"].max())
    ipo_depth = (ipo_high - float(ipo_window["Low"].min())) / ipo_high * 100.0
    prior_20_high = (
        float(data["High"].iloc[-21:-1].max()) if len(data) >= 21 else np.nan
    )
    recent_ipo = bool(metadata.get("recent_ipo_overlay", ipo_age_days <= 730))

    row = {
        "symbol": symbol,
        "company_name": metadata.get("company_name", ""),
        "industry": metadata.get("industry", ""),
        "listing_date": listing_date.date().isoformat(),
        "ipo_age_days": ipo_age_days,
        "liquidity_rank": metadata.get("liquidity_rank", pd.NA),
        "top_1000_liquid": bool(metadata.get("top_1000_liquid", False)),
        "recent_ipo_overlay": recent_ipo,
        "history_sessions": len(data),
        "scan_date": as_of_date.date().isoformat(),
        "price_date": pd.Timestamp(data.index[-1]).date().isoformat(),
        "latest_open": float(data["Open"].iloc[-1]),
        "latest_high": float(data["High"].iloc[-1]),
        "latest_low": float(data["Low"].iloc[-1]),
        "latest_close": latest_close,
        "latest_volume": float(data["Volume"].iloc[-1]),
        "previous_close": float(close.iloc[-2]) if len(data) >= 2 else np.nan,
        "return_20d": _return(close, 20),
        "return_63d": _return(close, 63),
        "return_126d": _return(close, 126),
        "return_189d": _return(close, 189),
        "return_252d": _return(close, 252),
        "sma20": averages[20],
        "sma50": averages[50],
        "sma150": averages[150],
        "sma200": averages[200],
        "momentum_eligibility": "ELIGIBLE" if len(data) >= 253 else "NOT ELIGIBLE",
        "vcp_eligibility": "ELIGIBLE" if len(data) >= 273 else "NOT ELIGIBLE",
        "nr7": bool(len(data) >= 7 and last_range <= float(ranges.tail(7).min())),
        "three_close_band_pct": (
            (float(close.tail(3).max()) - float(close.tail(3).min()))
            / float(close.tail(3).min())
            * 100.0
            if len(data) >= 3
            else np.nan
        ),
        "atr14_pct": current_atr,
        "atr14_average_50_pct": atr_average_50,
        "atr_contraction": bool(
            np.isfinite(current_atr)
            and np.isfinite(atr_average_50)
            and current_atr < atr_average_50
        ),
        "average_volume_20d": average_volume_20,
        "volume_ratio_20d": volume_ratio,
        "daily_close_position": daily_position,
        "daily_range": last_range,
        "median_range_20d": range_median_20,
        "distance_from_20d_high_pct": close_distance_20,
        "accumulation_day": bool(
            len(data) >= 21
            and latest_close > float(close.iloc[-2])
            and volume_ratio >= 1.5
            and daily_position >= 0.5
        ),
        "volume_dry_up": bool(
            len(data) >= 21
            and volume_ratio <= 0.5
            and close_distance_20 <= 5.0
            and last_range <= range_median_20
        ),
        "gap_pct": gap_pct,
        "gap_and_hold": bool(
            len(data) >= 2
            and gap_pct >= 3.0
            and latest_close >= float(close.iloc[-2])
            and daily_position >= 0.5
        ),
        "daily_inside_bar": daily_inside,
        "double_inside_bar": double_inside,
        "weekly_inside_bar": _weekly_inside(data),
        "ipo_base_depth_pct": ipo_depth,
        "prior_20_high": prior_20_high,
        "ipo_base": bool(recent_ipo and len(data) >= 15 and ipo_depth <= 20.0),
        "ipo_momentum": bool(
            recent_ipo
            and len(data) >= 21
            and latest_close > averages[20]
            and _return(close, 20) >= 10.0
        ),
        "ipo_breakout": bool(
            recent_ipo
            and len(data) >= 21
            and latest_close > prior_20_high
            and volume_ratio >= 1.5
        ),
    }
    row.update(_swing_resistance(data))
    row.update(_flag_pennant(data))
    row.update(_rs_line_features(data, benchmark))
    return row


def _merge_extra(base: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    if extra.empty or "symbol" not in extra:
        return base
    additions = [column for column in extra.columns if column == "symbol" or column not in base]
    return base.merge(extra.loc[:, additions], on="symbol", how="left")


def build_feature_matrix(
    histories: dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    benchmark: pd.DataFrame,
    rankings: pd.DataFrame,
    setups: pd.DataFrame,
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    metadata = universe.set_index("symbol")
    rows = [
        _one_symbol_features(symbol, frame, metadata.loc[symbol], benchmark, as_of)
        for symbol, frame in histories.items()
        if symbol in metadata.index
    ]
    if not rows:
        result = pd.DataFrame(columns=["symbol", "history_sessions", "price_date"])
    else:
        result = pd.DataFrame(rows)
        result["history_status"] = "COMPLETE"
    missing_symbols = universe.loc[~universe["symbol"].isin(histories)].copy()
    if not missing_symbols.empty:
        missing_rows = missing_symbols.copy()
        missing_rows["history_sessions"] = 0
        missing_rows["price_date"] = pd.NA
        missing_rows["scan_date"] = pd.Timestamp(as_of).date().isoformat()
        missing_rows["history_status"] = "SCAN INCOMPLETE"
        result = pd.concat([result, missing_rows], ignore_index=True, sort=False)
    result = _merge_extra(result, rankings)
    result = _merge_extra(result, setups)
    return result.sort_values("symbol", ignore_index=True)


def history_evidence(histories: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for symbol, history in histories.items():
        frame = history.copy().sort_index().reset_index(names="date")
        frame.insert(0, "symbol", symbol)
        frame["week_ending"] = (
            pd.to_datetime(frame["date"]).dt.to_period("W-FRI").dt.end_time.dt.normalize()
        )
        frames.append(
            frame.loc[
                :, ["symbol", "date", "Open", "High", "Low", "Close", "Volume", "week_ending"]
            ]
        )
    if not frames:
        return pd.DataFrame(
            columns=[
                "symbol",
                "date",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
                "week_ending",
            ]
        )
    return pd.concat(frames, ignore_index=True)
