"""Auditable preset screener catalogue and evaluation engine."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .models import ScreenerState


@dataclass(frozen=True)
class ScreenerDefinition:
    slug: str
    category: str
    label: str
    description: str
    required_fields: tuple[str, ...]
    defaults: Mapping[str, float | int | bool] = field(default_factory=dict)


def _definition(
    slug: str,
    category: str,
    label: str,
    description: str,
    required_fields: tuple[str, ...],
    **defaults: float | bool,
) -> ScreenerDefinition:
    return ScreenerDefinition(
        slug, category, label, description, required_fields, defaults
    )


SCREENER_CATALOG = {
    item.slug: item
    for item in (
        _definition(
            "horizontal_resistance",
            "Horizontal resistance",
            "Horizontal resistance",
            "Repeated highs clustered near a resistance level.",
            (
                "resistance_touches",
                "resistance_dispersion_pct",
                "distance_to_resistance_pct",
            ),
            minimum_touches=3,
            maximum_dispersion_pct=2.0,
            maximum_below_resistance_pct=5.0,
            maximum_above_resistance_pct=2.0,
        ),
        _definition("nr7", "Tight setup", "NR7", "Narrowest range in seven sessions.", ("nr7",)),
        _definition(
            "three_tight_closes",
            "Tight setup",
            "3 tight closes",
            "Three consecutive closes within a compact band.",
            ("three_close_band_pct",),
            maximum_close_band_pct=1.5,
        ),
        _definition(
            "atr_contraction",
            "Tight setup",
            "ATR contraction",
            "Current ATR is below its 50-session average.",
            ("atr14_pct", "atr14_average_50_pct"),
            maximum_atr_ratio=1.0,
        ),
        _definition(
            "ipo_base",
            "IPO scanner",
            "IPO base",
            "Recent IPO trading in a bounded base.",
            ("recent_ipo_overlay", "ipo_base_depth_pct"),
            maximum_base_depth_pct=20.0,
        ),
        _definition(
            "ipo_momentum",
            "IPO scanner",
            "IPO momentum",
            "Recent IPO above its 20-day average with positive momentum.",
            ("recent_ipo_overlay", "latest_close", "sma20", "return_20d"),
            minimum_return_20d_pct=10.0,
        ),
        _definition(
            "ipo_breakout",
            "IPO scanner",
            "IPO breakout",
            "Recent IPO clearing its prior 20-day high on volume.",
            (
                "recent_ipo_overlay",
                "latest_close",
                "prior_20_high",
                "volume_ratio_20d",
            ),
            minimum_volume_ratio=1.5,
        ),
        _definition(
            "rs_high_before_price_high",
            "RS high before price high",
            "RS high before price high",
            "Relative-strength line reaches a high before price does.",
            (
                "rs_line_eligibility",
                "rs_line_distance_from_high_pct",
                "price_distance_from_high_pct",
            ),
            maximum_rs_distance_pct=0.0,
            minimum_price_distance_pct=0.01,
        ),
        _definition(
            "momentum",
            "Momentum scanner",
            "Momentum scanner",
            "High RS with aligned 50, 150 and 200-day averages.",
            ("rs_rating", "latest_close", "sma50", "sma150", "sma200", "return_63d"),
            minimum_rs_rating=80,
            minimum_return_63d_pct=0.0,
            require_ma_alignment=True,
        ),
        _definition(
            "relative_volume_surge",
            "Volume screeners",
            "Relative volume surge",
            "Volume at least twice the 20-session average.",
            ("volume_ratio_20d",),
            minimum_volume_ratio=2.0,
        ),
        _definition(
            "accumulation_day",
            "Volume screeners",
            "Accumulation day",
            "Positive close with high volume near the top of the range.",
            ("latest_close", "previous_close", "volume_ratio_20d", "daily_close_position"),
            minimum_volume_ratio=1.5,
            minimum_close_position=0.5,
        ),
        _definition(
            "volume_dry_up",
            "Volume screeners",
            "Volume dry-up",
            "Quiet volume and range close to the 20-day high.",
            (
                "volume_ratio_20d",
                "distance_from_20d_high_pct",
                "daily_range",
                "median_range_20d",
            ),
            maximum_volume_ratio=0.5,
            maximum_distance_from_high_pct=5.0,
            maximum_range_ratio=1.0,
        ),
        _definition(
            "vcp",
            "VCP",
            "VCP",
            "Auditable volatility-contraction score.",
            ("vcp_stars",),
            minimum_stars=4,
        ),
        _definition(
            "flags_pennants",
            "Flags & pennants",
            "Flags & pennants",
            "Strong pole followed by a shallow, quiet consolidation.",
            (
                "pole_gain_pct",
                "consolidation_sessions",
                "consolidation_depth_pct",
                "consolidation_volume_ratio",
            ),
            minimum_pole_gain_pct=15.0,
            minimum_consolidation_sessions=5,
            maximum_consolidation_sessions=20,
            maximum_consolidation_depth_pct=12.0,
            maximum_consolidation_volume_ratio=1.0,
        ),
        _definition(
            "results_due",
            "Earnings screeners",
            "Results due",
            "Official NSE results meeting due soon.",
            ("scan_date",),
            maximum_calendar_days=14,
        ),
        _definition(
            "fresh_results",
            "Earnings screeners",
            "Fresh results",
            "Official NSE financial filing published recently.",
            ("scan_date",),
            maximum_business_sessions=5,
        ),
        _definition(
            "post_results_gap_up",
            "Earnings screeners",
            "Post-results gap up",
            "Gap-up response on the filing session with strong volume.",
            ("scan_date", "price_date", "gap_pct", "volume_ratio_20d"),
            minimum_gap_pct=4.0,
            minimum_volume_ratio=1.5,
        ),
        _definition(
            "gap_up",
            "Gap screeners",
            "Gap up",
            "Opening gap above the prior close.",
            ("gap_pct",),
            minimum_gap_pct=3.0,
        ),
        _definition(
            "gap_down",
            "Gap screeners",
            "Gap down",
            "Opening gap below the prior close.",
            ("gap_pct",),
            minimum_gap_pct=3.0,
        ),
        _definition(
            "gap_and_hold",
            "Gap screeners",
            "Gap and hold",
            "Gap-up session that holds above the prior close.",
            ("gap_pct", "gap_and_hold"),
            minimum_gap_pct=3.0,
        ),
        _definition(
            "daily_inside_bar",
            "Inside bar",
            "Daily inside bar",
            "Daily range fully inside the prior session.",
            ("daily_inside_bar",),
        ),
        _definition(
            "double_inside_bar",
            "Inside bar",
            "Double inside bar",
            "Two consecutive inside-bar sessions.",
            ("double_inside_bar",),
        ),
        _definition(
            "weekly_inside_bar",
            "Inside bar",
            "Weekly inside bar",
            "Current completed weekly range inside the prior week.",
            ("weekly_inside_bar",),
        ),
    )
}

EARNINGS_SCREENERS = {"results_due", "fresh_results", "post_results_gap_up"}


def default_thresholds(slug: str) -> dict[str, float | int | bool]:
    """Return a mutable copy of a preset's default thresholds."""
    return dict(SCREENER_CATALOG[slug].defaults)


def _missing(row: pd.Series, fields: tuple[str, ...]) -> list[str]:
    return [name for name in fields if name not in row or pd.isna(row[name])]


def _as_date(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()


def _next_business_day(value: pd.Timestamp) -> pd.Timestamp:
    return (value.normalize() + pd.offsets.BDay(1)).normalize()


def _events_for(events: pd.DataFrame, symbol: str, event_type: str) -> pd.DataFrame:
    if events.empty or not {"symbol", "event_type"}.issubset(events.columns):
        return events.iloc[0:0]
    return events.loc[
        events["symbol"].eq(symbol) & events["event_type"].eq(event_type)
    ]


def _technical_match(slug: str, row: pd.Series, t: Mapping[str, Any]) -> bool:
    checks: dict[str, Callable[[], bool]] = {
        "horizontal_resistance": lambda: (
            row.resistance_touches >= t["minimum_touches"]
            and row.resistance_dispersion_pct <= t["maximum_dispersion_pct"]
            and -t["maximum_above_resistance_pct"]
            <= row.distance_to_resistance_pct
            <= t["maximum_below_resistance_pct"]
        ),
        "nr7": lambda: bool(row.nr7),
        "three_tight_closes": lambda: row.three_close_band_pct
        <= t["maximum_close_band_pct"],
        "atr_contraction": lambda: row.atr14_pct
        <= row.atr14_average_50_pct * t["maximum_atr_ratio"],
        "ipo_base": lambda: bool(row.recent_ipo_overlay)
        and row.ipo_base_depth_pct <= t["maximum_base_depth_pct"],
        "ipo_momentum": lambda: bool(row.recent_ipo_overlay)
        and row.latest_close > row.sma20
        and row.return_20d >= t["minimum_return_20d_pct"],
        "ipo_breakout": lambda: bool(row.recent_ipo_overlay)
        and row.latest_close > row.prior_20_high
        and row.volume_ratio_20d >= t["minimum_volume_ratio"],
        "rs_high_before_price_high": lambda: row.rs_line_eligibility == "ELIGIBLE"
        and row.rs_line_distance_from_high_pct <= t["maximum_rs_distance_pct"]
        and row.price_distance_from_high_pct >= t["minimum_price_distance_pct"],
        "momentum": lambda: row.rs_rating >= t["minimum_rs_rating"]
        and row.return_63d >= t["minimum_return_63d_pct"]
        and (
            not t["require_ma_alignment"]
            or row.latest_close > row.sma50 > row.sma150 > row.sma200
        ),
        "relative_volume_surge": lambda: row.volume_ratio_20d
        >= t["minimum_volume_ratio"],
        "accumulation_day": lambda: row.latest_close > row.previous_close
        and row.volume_ratio_20d >= t["minimum_volume_ratio"]
        and row.daily_close_position >= t["minimum_close_position"],
        "volume_dry_up": lambda: row.volume_ratio_20d <= t["maximum_volume_ratio"]
        and row.distance_from_20d_high_pct <= t["maximum_distance_from_high_pct"]
        and row.daily_range <= row.median_range_20d * t["maximum_range_ratio"],
        "vcp": lambda: row.vcp_stars >= t["minimum_stars"],
        "flags_pennants": lambda: row.pole_gain_pct >= t["minimum_pole_gain_pct"]
        and t["minimum_consolidation_sessions"]
        <= row.consolidation_sessions
        <= t["maximum_consolidation_sessions"]
        and row.consolidation_depth_pct <= t["maximum_consolidation_depth_pct"]
        and row.consolidation_volume_ratio
        <= t["maximum_consolidation_volume_ratio"],
        "gap_up": lambda: row.gap_pct >= t["minimum_gap_pct"],
        "gap_down": lambda: row.gap_pct <= -t["minimum_gap_pct"],
        "gap_and_hold": lambda: row.gap_pct >= t["minimum_gap_pct"]
        and bool(row.gap_and_hold),
        "daily_inside_bar": lambda: bool(row.daily_inside_bar),
        "double_inside_bar": lambda: bool(row.double_inside_bar),
        "weekly_inside_bar": lambda: bool(row.weekly_inside_bar),
    }
    return checks[slug]()


def _earnings_match(
    slug: str,
    row: pd.Series,
    events: pd.DataFrame,
    thresholds: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    scan_date = _as_date(row.scan_date)
    if slug == "results_due":
        candidates = _events_for(events, row.symbol, "RESULTS_DUE")
        dates = pd.to_datetime(candidates.get("event_date"), errors="coerce")
        dates = dates[(dates >= scan_date) & (dates <= scan_date + pd.Timedelta(days=thresholds["maximum_calendar_days"]))]
    else:
        candidates = _events_for(events, row.symbol, "RESULT_FILED")
        dates = pd.to_datetime(candidates.get("event_date"), errors="coerce")
        if slug == "fresh_results":
            historical = dates <= scan_date
            recent = dates.apply(
                lambda value: len(pd.bdate_range(value, scan_date)) - 1
                <= thresholds["maximum_business_sessions"]
            ).astype(bool)
            dates = dates.loc[historical & recent]
        else:
            price_date = _as_date(row.price_date)
            matched_dates = []
            for _, event in candidates.iterrows():
                broadcast = pd.Timestamp(event.get("broadcast_at"))
                if pd.isna(broadcast):
                    target = _as_date(event.event_date)
                else:
                    target = _as_date(broadcast)
                    if broadcast.hour > 15 or (broadcast.hour == 15 and broadcast.minute >= 30):
                        target = _next_business_day(target)
                if target == price_date:
                    matched_dates.append(_as_date(event.event_date))
            dates = pd.Series(matched_dates, dtype="datetime64[ns]")
            if not dates.empty and not (
                row.gap_pct >= thresholds["minimum_gap_pct"]
                and row.volume_ratio_20d >= thresholds["minimum_volume_ratio"]
            ):
                dates = dates.iloc[0:0]
    matched = not dates.empty
    return matched, {"matching_event_dates": [str(value.date()) for value in dates]}


def _json_value(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value):
        return None
    return value


def evaluate_screener(
    slug: str,
    features: pd.DataFrame,
    events: pd.DataFrame,
    thresholds: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Evaluate one preset without converting unknown data to a negative result."""
    definition = SCREENER_CATALOG[slug]
    applied = default_thresholds(slug)
    applied.update(thresholds or {})
    columns = [
        "symbol",
        "company_name",
        "listing_date",
        "liquidity_rank",
        "price_date",
        "screener",
        "label",
        "state",
        "reason",
        "evidence",
    ]
    if features.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    events_status = events.attrs.get("status", "COMPLETE")
    for _, feature in features.iterrows():
        missing = _missing(feature, definition.required_fields)
        evidence = {
            name: _json_value(feature.get(name))
            for name in definition.required_fields
            if name in feature
        }
        evidence["thresholds"] = applied
        benchmark_incomplete = (
            slug == "rs_high_before_price_high"
            and feature.get("benchmark_status", "COMPLETE") != "COMPLETE"
        )
        if benchmark_incomplete:
            state = ScreenerState.INCOMPLETE
            reason = "Nifty 50 benchmark history was unavailable."
        elif slug in EARNINGS_SCREENERS and events_status != "COMPLETE":
            state = ScreenerState.INCOMPLETE
            reason = "Official NSE earnings events were unavailable."
        elif missing:
            state = ScreenerState.NOT_ELIGIBLE
            reason = f"Missing required evidence: {', '.join(missing)}"
        else:
            if slug in EARNINGS_SCREENERS:
                matched, event_evidence = _earnings_match(slug, feature, events, applied)
                evidence.update(event_evidence)
            else:
                matched = _technical_match(slug, feature, applied)
            state = ScreenerState.MATCH if matched else ScreenerState.NO_MATCH
            reason = "All conditions passed." if matched else "One or more conditions failed."
        rows.append(
            {
                "symbol": feature.get("symbol"),
                "company_name": feature.get("company_name"),
                "listing_date": feature.get("listing_date"),
                "liquidity_rank": feature.get("liquidity_rank"),
                "price_date": feature.get("price_date"),
                "screener": slug,
                "label": definition.label,
                "state": state.value,
                "reason": reason,
                "evidence": json.dumps(evidence, sort_keys=True),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def evaluate_all_screeners(
    features: pd.DataFrame, events: pd.DataFrame
) -> pd.DataFrame:
    """Evaluate every preset in stable catalogue order."""
    return pd.concat(
        [evaluate_screener(slug, features, events) for slug in SCREENER_CATALOG],
        ignore_index=True,
    )


def multiple_scan_matches(
    results: pd.DataFrame, selected_slugs: list[str], minimum_matches: int
) -> pd.DataFrame:
    """Return symbols matching at least N of the selected preset screeners."""
    selected = results.loc[
        results["screener"].isin(selected_slugs)
        & results["state"].eq(ScreenerState.MATCH.value)
    ].copy()
    columns = [
        "symbol",
        "company_name",
        "listing_date",
        "liquidity_rank",
        "price_date",
        "match_count",
        "matched_screeners",
    ]
    if selected.empty:
        return pd.DataFrame(columns=columns)
    label_order = {
        slug: (index, SCREENER_CATALOG[slug].label)
        for index, slug in enumerate(selected_slugs)
    }
    rows = []
    for symbol, group in selected.groupby("symbol", sort=True):
        slugs = list(dict.fromkeys(group["screener"]))
        if len(slugs) < minimum_matches:
            continue
        slugs.sort(key=lambda value: label_order[value][0])
        first = group.iloc[0]
        rows.append(
            {
                "symbol": symbol,
                "company_name": first.get("company_name"),
                "listing_date": first.get("listing_date"),
                "liquidity_rank": first.get("liquidity_rank"),
                "price_date": first.get("price_date"),
                "match_count": len(slugs),
                "matched_screeners": " | ".join(label_order[slug][1] for slug in slugs),
            }
        )
    return pd.DataFrame(rows, columns=columns)
