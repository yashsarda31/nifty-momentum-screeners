"""Versioned local persistence and evaluation for AND-based custom screeners."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from operator import eq, ge, gt, le, lt, ne
from pathlib import Path
from typing import Any

import pandas as pd

from .models import ScreenerState

OPERATORS = {">": gt, ">=": ge, "<": lt, "<=": le, "==": eq, "!=": ne}


@dataclass(frozen=True)
class Rule:
    field: str
    operator: str
    value: float | str

    def __post_init__(self) -> None:
        if not self.field.strip():
            raise ValueError("rule field cannot be empty")
        if self.operator not in OPERATORS:
            raise ValueError(f"unsupported operator: {self.operator}")
        if isinstance(self.value, (int, float)) and not math.isfinite(self.value):
            raise ValueError("numeric rule value must be finite")
        if not isinstance(self.value, (int, float, str)):
            raise TypeError("rule value must be a finite number or string")


@dataclass(frozen=True)
class CustomScreener:
    name: str
    rules: tuple[Rule, ...]

    def __post_init__(self) -> None:
        clean_name = self.name.strip()
        if not clean_name:
            raise ValueError("screener name cannot be empty")
        if not self.rules:
            raise ValueError("custom screener must contain at least one rule")
        object.__setattr__(self, "name", clean_name)


def _decode_store(payload: dict[str, Any]) -> dict[str, CustomScreener]:
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported custom screener schema version")
    screeners = {}
    for name, data in payload.get("screeners", {}).items():
        rules = tuple(Rule(**rule) for rule in data.get("rules", []))
        screeners[name] = CustomScreener(name, rules)
    return screeners


def load_store(path: Path) -> dict[str, CustomScreener]:
    """Load the local custom-screener store; a missing file is an empty store."""
    path = Path(path)
    if not path.exists():
        return {}
    return _decode_store(json.loads(path.read_text(encoding="utf-8")))


def _encode_store(screeners: dict[str, CustomScreener]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "screeners": {
            name: {
                "rules": [
                    {
                        "field": rule.field,
                        "operator": rule.operator,
                        "value": rule.value,
                    }
                    for rule in screener.rules
                ]
            }
            for name, screener in sorted(screeners.items())
        },
    }


def _write_store(path: Path, screeners: dict[str, CustomScreener]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(_encode_store(screeners), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def save_screener(
    path: Path, screener: CustomScreener, overwrite: bool = False
) -> None:
    screeners = load_store(path)
    if screener.name in screeners and not overwrite:
        raise FileExistsError(f"custom screener already exists: {screener.name}")
    screeners[screener.name] = screener
    _write_store(path, screeners)


def rename_screener(path: Path, old: str, new: str) -> None:
    screeners = load_store(path)
    if old not in screeners:
        raise KeyError(old)
    clean_name = new.strip()
    if clean_name in screeners and clean_name != old:
        raise FileExistsError(f"custom screener already exists: {clean_name}")
    renamed = CustomScreener(clean_name, screeners.pop(old).rules)
    screeners[renamed.name] = renamed
    _write_store(path, screeners)


def delete_screener(path: Path, name: str) -> None:
    screeners = load_store(path)
    if name not in screeners:
        raise KeyError(name)
    del screeners[name]
    _write_store(path, screeners)


def _evaluate_rule(rule: Rule, value: Any) -> bool | None:
    if pd.isna(value):
        return None
    if isinstance(rule.value, (int, float)):
        try:
            candidate = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(candidate):
            return None
        return bool(OPERATORS[rule.operator](candidate, float(rule.value)))
    if rule.operator not in {"==", "!="}:
        return None
    return bool(OPERATORS[rule.operator](str(value), rule.value))


def evaluate_custom(screener: CustomScreener, features: pd.DataFrame) -> pd.DataFrame:
    """Evaluate custom rules with AND semantics and explicit ineligibility."""
    rows = []
    for _, feature in features.iterrows():
        missing = [rule.field for rule in screener.rules if rule.field not in feature]
        evaluations = []
        if not missing:
            evaluations = [
                _evaluate_rule(rule, feature[rule.field]) for rule in screener.rules
            ]
        invalid = []
        if not missing:
            invalid = [
                rule.field
                for rule, result in zip(screener.rules, evaluations, strict=True)
                if result is None
            ]
        unavailable = list(dict.fromkeys(missing + invalid))
        if unavailable:
            state = ScreenerState.NOT_ELIGIBLE
            reason = f"Missing or invalid evidence: {', '.join(unavailable)}"
        elif all(evaluations):
            state = ScreenerState.MATCH
            reason = "All custom rules passed."
        else:
            state = ScreenerState.NO_MATCH
            reason = "One or more custom rules failed."
        rows.append(
            {
                "symbol": feature.get("symbol"),
                "company_name": feature.get("company_name"),
                "price_date": feature.get("price_date"),
                "screener": screener.name,
                "state": state.value,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)
