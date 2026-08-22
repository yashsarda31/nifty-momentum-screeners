# Scanner Reliability, Freshness, and Usability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing NSE scanner resilient to stale data, provider and artifact failures, and cumbersome result inspection without changing any financial signal.

**Architecture:** Keep financial calculations in their existing modules. Add pure, typed dashboard-support helpers for freshness and health summaries, validate persisted bundles at the read boundary, convert unexpected pipeline-stage failures into explicit incomplete runs, and keep Streamlit functions focused on rendering and session actions.

**Tech Stack:** Python 3.11+, pandas, Streamlit 1.61, Plotly, pytest, Streamlit AppTest, Ruff, PowerShell/RTK.

## Global Constraints

- Preserve the top 1,000 NSE equities by 60-session median traded value plus the existing recent-IPO overlay.
- Preserve every preset screener, custom screener, TradingView export, momentum formula, VCP score, and completed-candle rule.
- Yahoo startup prices remain in `st.session_state` only; do not add shared, TTL, process, or disk caching.
- Provider failure must remain `SCAN INCOMPLETE`, never `NO BREAKOUTS`.
- Existing scan bundles must not be deleted or rewritten.
- Add no screening strategies, alerts, backtests, broker links, background polling, or automatic full scans.

## File Structure

- Create `src/nifty_vcp/dashboard_support.py`: pure freshness, session invalidation, and health-summary functions.
- Modify `app.py`: bundle validation, controlled scan/load feedback, freshness/health rendering, and sidebar refresh actions.
- Modify `src/nifty_vcp/pipeline.py`: stage-aware fatal diagnostics for unexpected failures.
- Modify `screener_ui.py`: pure result filtering plus search/state controls.
- Modify `tests/test_app.py`: dashboard helper, bundle-loading, and rendering regressions.
- Modify `tests/test_pipeline.py`: post-universe failure semantics.
- Modify `tests/test_screener_ui.py` and `tests/streamlit_screener_fixture.py`: visible-result filtering and export interactions.
- Modify `README.md`: document freshness, refresh, and incomplete-run behavior.

---

### Task 1: Freshness and Session-Refresh Helpers

**Files:**
- Create: `src/nifty_vcp/dashboard_support.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Produces: `ScanFreshness`, `scan_freshness(manifest, now) -> ScanFreshness`, and `clear_startup_price_state(session_state, startup_key, enriched_key) -> None`.
- Consumes: an ISO-8601 `manifest["finished_at"]` and any mutable Streamlit-like session mapping.

- [ ] **Step 1: Write failing freshness and invalidation tests**

Add these imports and tests to `tests/test_app.py`:

```python
from nifty_vcp.dashboard_support import (
    clear_startup_price_state,
    scan_freshness,
)


def test_scan_freshness_marks_older_calendar_date_stale():
    freshness = scan_freshness(
        {"finished_at": "2026-08-20T16:00:00+05:30"},
        datetime(2026, 8, 22, 9, 0, tzinfo=TZ),
    )

    assert freshness.finished_at.isoformat() == "2026-08-20T16:00:00+05:30"
    assert freshness.age_days == 2
    assert freshness.is_stale is True
    assert freshness.label == "2 days old"


def test_scan_freshness_labels_same_day_current():
    freshness = scan_freshness(
        {"finished_at": "2026-08-22T08:00:00+05:30"},
        datetime(2026, 8, 22, 9, 0, tzinfo=TZ),
    )

    assert freshness.age_days == 0
    assert freshness.is_stale is False
    assert freshness.label == "today"


def test_scan_freshness_handles_missing_or_invalid_timestamp():
    missing = scan_freshness({}, datetime(2026, 8, 22, 9, 0, tzinfo=TZ))
    invalid = scan_freshness(
        {"finished_at": "not-a-date"},
        datetime(2026, 8, 22, 9, 0, tzinfo=TZ),
    )

    assert missing.finished_at is None
    assert missing.label == "scan time unavailable"
    assert invalid.finished_at is None
    assert invalid.is_stale is True


def test_clear_startup_price_state_preserves_unrelated_session_values():
    session = {
        STARTUP_PRICES_KEY: object(),
        ENRICHED_BUNDLE_KEY: object(),
        "screener_menu": "VCP",
    }

    clear_startup_price_state(
        session,
        STARTUP_PRICES_KEY,
        ENRICHED_BUNDLE_KEY,
    )

    assert STARTUP_PRICES_KEY not in session
    assert ENRICHED_BUNDLE_KEY not in session
    assert session["screener_menu"] == "VCP"
```

- [ ] **Step 2: Run the tests and verify the expected import failure**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q tests/test_app.py -k "freshness or clear_startup"
```

Expected: collection fails because `nifty_vcp.dashboard_support` does not exist.

- [ ] **Step 3: Implement the pure helper module**

Create `src/nifty_vcp/dashboard_support.py` with:

```python
"""Pure helpers for dashboard freshness, health, and session state."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ScanFreshness:
    finished_at: datetime | None
    age_days: int | None
    label: str
    is_stale: bool


def scan_freshness(manifest: dict, now: datetime) -> ScanFreshness:
    raw = manifest.get("finished_at")
    try:
        finished = pd.Timestamp(raw).to_pydatetime()
    except (TypeError, ValueError):
        return ScanFreshness(None, None, "scan time unavailable", True)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=now.tzinfo)
    local_now = now.astimezone(finished.tzinfo)
    age_days = max(0, (local_now.date() - finished.date()).days)
    if age_days == 0:
        label = "today"
    elif age_days == 1:
        label = "1 day old"
    else:
        label = f"{age_days} days old"
    return ScanFreshness(finished, age_days, label, age_days > 1)


def clear_startup_price_state(
    session_state: MutableMapping[str, Any],
    startup_key: str,
    enriched_key: str,
) -> None:
    session_state.pop(startup_key, None)
    session_state.pop(enriched_key, None)
```

- [ ] **Step 4: Run the focused tests**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q tests/test_app.py -k "freshness or clear_startup"
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the helper**

```powershell
rtk git add src/nifty_vcp/dashboard_support.py tests/test_app.py
rtk git commit -m "feat: add scanner freshness state"
```

---

### Task 2: Validate Published Bundles at the Read Boundary

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Produces: `RunBundleError`, `_validated_run_path(root, run_directory) -> Path`, and controlled `load_latest_run(...)` failures.
- Consumes: Task 1 helpers only at final UI integration, not in the loader.

- [ ] **Step 1: Write failing bundle-validation tests**

Add to `tests/test_app.py`:

```python
from app import RunBundleError


def test_latest_pointer_cannot_escape_output_root(tmp_path):
    (tmp_path / "latest.json").write_text(
        json.dumps({"run_directory": "../outside"}), encoding="utf-8"
    )

    with pytest.raises(RunBundleError, match="outside the output root"):
        load_latest_run(tmp_path)


def test_malformed_latest_pointer_has_controlled_error(tmp_path):
    (tmp_path / "latest.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(RunBundleError, match="latest.json"):
        load_latest_run(tmp_path)


def test_missing_required_artifact_has_controlled_error(tmp_path):
    run = tmp_path / "run-1"
    run.mkdir()
    (tmp_path / "latest.json").write_text(
        json.dumps({"run_directory": "run-1"}), encoding="utf-8"
    )
    (run / "run_manifest.json").write_text(
        json.dumps({"status": "COMPLETE"}), encoding="utf-8"
    )

    with pytest.raises(RunBundleError, match="all_rankings.csv"):
        load_latest_run(tmp_path)


def test_partial_schema_two_bundle_reports_why_screeners_are_unavailable(tmp_path):
    run = write_schema_one_bundle(tmp_path, "run-partial")
    manifest = {"status": "COMPLETE", "schema_version": 2}
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    pd.DataFrame({"symbol": ["AAA"]}).to_csv(
        run / "selected_universe.csv", index=False
    )

    bundle = load_latest_run(tmp_path)

    assert bundle["screeners_available"] is False
    assert "screener_features.csv" in bundle["screeners_unavailable_reason"]
```

Add this local helper above the bundle tests and reuse it from the existing
schema-one loader test:

```python
def write_schema_one_bundle(tmp_path, name="run-1"):
    run = tmp_path / name
    run.mkdir()
    (tmp_path / "latest.json").write_text(
        json.dumps({"run_directory": name}), encoding="utf-8"
    )
    (run / "run_manifest.json").write_text(
        json.dumps({"status": "COMPLETE"}), encoding="utf-8"
    )
    for filename in (
        "all_rankings.csv",
        "high_rs_setups.csv",
        "live_breakouts.csv",
        "exclusions.csv",
    ):
        pd.DataFrame({"symbol": ["AAA"]}).to_csv(run / filename, index=False)
    pd.DataFrame(
        {"symbol": ["AAA"], "date": ["2026-08-11"], "Close": [100.0]}
    ).to_csv(run / "chart_history.csv.gz", index=False, compression="gzip")
    return run
```

- [ ] **Step 2: Run the tests and verify they fail on uncontrolled exceptions**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q tests/test_app.py -k "pointer or required_artifact"
```

Expected: failure because `RunBundleError` and validation do not exist.

- [ ] **Step 3: Add path and required-file validation**

Add near the bundle constants in `app.py`:

```python
REQUIRED_RUN_FILES = (
    "run_manifest.json",
    "all_rankings.csv",
    "high_rs_setups.csv",
    "live_breakouts.csv",
    "exclusions.csv",
    "chart_history.csv.gz",
)


class RunBundleError(RuntimeError):
    """A published scan bundle cannot be loaded safely."""


def _validated_run_path(root: Path, run_directory: object) -> Path:
    if not isinstance(run_directory, str) or not run_directory.strip():
        raise RunBundleError("latest.json has no valid run_directory")
    resolved_root = root.resolve()
    candidate = (resolved_root / run_directory).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise RunBundleError("latest.json points outside the output root")
    missing = [name for name in REQUIRED_RUN_FILES if not (candidate / name).is_file()]
    if missing:
        raise RunBundleError(
            f"Published run {candidate.name} is missing {', '.join(missing)}"
        )
    return candidate
```

Update `load_latest_run` to catch JSON and I/O failures, validate the path, and pass the validated directory name to `_load_run_bundle`:

```python
def load_latest_run(output_root: str | Path = OUTPUT_ROOT) -> dict | None:
    root = Path(output_root)
    pointer = root / "latest.json"
    if not pointer.exists():
        return None
    try:
        latest = json.loads(pointer.read_text(encoding="utf-8"))
        run_path = _validated_run_path(root, latest.get("run_directory"))
        return _load_run_bundle(
            str(root.resolve()),
            run_path.name,
            pointer.stat().st_mtime_ns,
        )
    except RunBundleError:
        raise
    except (OSError, ValueError, KeyError, pd.errors.ParserError) as exc:
        raise RunBundleError(f"Could not read {pointer}: {exc}") from exc
```

Wrap the body of `_load_run_bundle` in the same controlled boundary by converting read/parse failures into `RunBundleError` with the run-directory name.
When a schema-two manifest is missing one or more screener artifacts, set
`screeners_available=False` and populate `screeners_unavailable_reason` with the
missing filenames; do not partially load the screener tables.

- [ ] **Step 4: Run loader tests and the existing bundle tests**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q tests/test_app.py -k "bundle or pointer or artifact"
```

Expected: all selected tests pass, including schema-one and schema-two bundle loading.

- [ ] **Step 5: Commit validated reads**

```powershell
rtk git add app.py tests/test_app.py
rtk git commit -m "fix: validate published scan bundles"
```

---

### Task 3: Convert Pipeline-Stage Failures into Incomplete Runs

**Files:**
- Modify: `src/nifty_vcp/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Produces: fatal manifests with `failure_stage` and `fatal_error`; `run_scan` still returns `ScanSummary`.
- Preserves: publisher failures raise and leave the previous `latest.json` pointer intact.

- [ ] **Step 1: Write failing stage-failure tests**

Add to `tests/test_pipeline.py`:

```python
def test_daily_history_failure_publishes_incomplete_stage_diagnostic(tmp_path):
    dependencies, published = make_dependencies()

    def fail_daily(*_args):
        raise RuntimeError("Yahoo daily unavailable")

    dependencies = PipelineDependencies(
        **{
            **dependencies.__dict__,
            "daily_loader": fail_daily,
        }
    )

    summary = run_scan(ScanConfig(), dependencies, output_root=tmp_path)

    assert summary.status == RunStatus.INCOMPLETE
    assert summary.outcome == "SCAN INCOMPLETE"
    assert published["manifest"]["failure_stage"] == "daily history"
    assert published["manifest"]["fatal_error"] == "Yahoo daily unavailable"


def test_publisher_failure_is_not_hidden(tmp_path):
    dependencies, _ = make_dependencies()

    def fail_publish(*_args):
        raise OSError("disk full")

    dependencies = PipelineDependencies(
        **{
            **dependencies.__dict__,
            "publisher": fail_publish,
        }
    )

    with pytest.raises(OSError, match="disk full"):
        run_scan(ScanConfig(), dependencies, output_root=tmp_path)
```

Also add `import pytest` at the top of the file.

- [ ] **Step 2: Run the focused tests and verify the daily failure escapes**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q tests/test_pipeline.py -k "failure"
```

Expected: the daily-loader test raises `RuntimeError` instead of returning an incomplete summary.

- [ ] **Step 3: Add stage tracking and fatal publication**

Extend `_fatal_manifest` in `src/nifty_vcp/pipeline.py`:

```python
def _fatal_manifest(
    started: datetime,
    finished: datetime,
    exc: Exception,
    stage: str,
) -> dict:
    return {
        "schema_version": 2,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "status": RunStatus.INCOMPLETE.value,
        "outcome": RunStatus.INCOMPLETE.value,
        "universe_source": UNIVERSE_URL,
        "price_source": YAHOO_SOURCE,
        "source_universe_count": 0,
        "universe_count": 0,
        "selected_universe_count": 0,
        "valid_history_count": 0,
        "historical_coverage": 0.0,
        "high_rs_count": 0,
        "valid_quote_count": 0,
        "quote_coverage": 0.0,
        "breakout_count": 0,
        "failure_stage": stage,
        "fatal_error": str(exc),
    }
```

In `run_scan`, set `stage` immediately before each externally fallible phase:

```python
stage = "universe"
try:
    universe = dependencies.universe_loader(config.request_timeout)
    stage = "daily history"
    histories, history_exclusions = dependencies.daily_loader(universe, started, config)
    stage = "universe selection"
    selected_universe = dependencies.universe_selector(
        universe, histories, started, config
    )
except Exception as exc:
    finished = datetime.now(tz=INDIA_TZ)
    manifest = _fatal_manifest(started, finished, exc, stage)
    output_path = dependencies.publisher(output_root, _empty_artifacts(), manifest)
    return ScanSummary(
        RunStatus.INCOMPLETE,
        RunStatus.INCOMPLETE.value,
        0,
        0,
        0,
        0,
        0,
        started,
        finished,
        output_path,
    )
```

Place the existing operations from universe loading through screener evaluation
inside this boundary without changing their formulas. Assign these exact labels
immediately before their dependency calls: `universe`, `daily history`,
`universe selection`, `relative-strength ranking`, `VCP scoring`, `latest quotes`,
`breakout classification`, `benchmark history`, `earnings events`,
`feature matrix`, and `screener evaluation`. The benchmark call keeps its existing
local fallback instead of reaching the fatal boundary. The final successful
publisher call stays after the boundary.

Do not include the final `dependencies.publisher(...)` call for a successful run inside that `try`; a disk failure must continue raising so atomic storage preserves the previous pointer. Keep the existing benchmark-specific fallback and earnings-status behavior.

- [ ] **Step 4: Run all pipeline and storage tests**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q tests/test_pipeline.py tests/test_storage.py
```

Expected: all tests pass and the storage atomicity regression remains green.

- [ ] **Step 5: Commit pipeline failure semantics**

```powershell
rtk git add src/nifty_vcp/pipeline.py tests/test_pipeline.py
rtk git commit -m "fix: publish incomplete scan diagnostics"
```

---

### Task 4: Render Freshness, Controlled Scan Feedback, and Scan Health

**Files:**
- Modify: `src/nifty_vcp/dashboard_support.py`
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Produces: `scan_health_summary(manifest, exclusions) -> dict[str, Any]`, `render_scan_freshness`, and `render_scan_health`.
- Consumes: Task 1 freshness/session helpers and Task 2 `RunBundleError`.

- [ ] **Step 1: Write failing health-summary and Streamlit-action tests**

Add to `tests/test_app.py`:

```python
from nifty_vcp.dashboard_support import scan_health_summary


def test_scan_health_summary_groups_exclusions_and_provider_status():
    summary = scan_health_summary(
        {
            "status": "SCAN INCOMPLETE",
            "universe_count": 10,
            "valid_history_count": 8,
            "high_rs_count": 4,
            "valid_quote_count": 3,
            "benchmark_status": "COMPLETE",
            "earnings_status": "SCAN INCOMPLETE",
            "started_at": "2026-08-22T08:00:00+05:30",
            "finished_at": "2026-08-22T08:03:30+05:30",
            "market_state": "OPEN",
        },
        pd.DataFrame(
            {
                "stage": ["history", "history", "quote"],
                "reason": ["stale", "stale", "missing"],
            }
        ),
    )

    assert summary["historical_coverage"] == pytest.approx(0.8)
    assert summary["quote_coverage"] == pytest.approx(0.75)
    assert summary["providers"] == {
        "Benchmark": "COMPLETE",
        "Earnings": "SCAN INCOMPLETE",
    }
    assert summary["elapsed_seconds"] == 210.0
    assert summary["market_state"] == "OPEN"
    assert summary["exclusion_groups"].to_dict("records") == [
        {"stage": "history", "reason": "stale", "count": 2},
        {"stage": "quote", "reason": "missing", "count": 1},
    ]


def test_refresh_price_action_clears_only_quote_state(monkeypatch):
    session = {
        STARTUP_PRICES_KEY: object(),
        ENRICHED_BUNDLE_KEY: object(),
        "leader_search": "TCS",
    }
    monkeypatch.setattr(dashboard_app.st, "session_state", session)
    monkeypatch.setattr(dashboard_app.st, "rerun", lambda: None)

    dashboard_app.refresh_session_prices()

    assert STARTUP_PRICES_KEY not in session
    assert ENRICHED_BUNDLE_KEY not in session
    assert session["leader_search"] == "TCS"
```

- [ ] **Step 2: Run focused tests and verify missing functions**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q tests/test_app.py -k "health_summary or refresh_price_action"
```

Expected: failure because health summary and refresh action are undefined.

- [ ] **Step 3: Implement the pure health summary**

Add to `src/nifty_vcp/dashboard_support.py`:

```python
def _coverage(valid: object, total: object) -> float:
    try:
        valid_count = int(valid)
        total_count = int(total)
    except (TypeError, ValueError):
        return 0.0
    return valid_count / total_count if total_count > 0 else 0.0


def scan_health_summary(manifest: dict, exclusions: pd.DataFrame) -> dict[str, Any]:
    required = {"stage", "reason"}
    if exclusions.empty or not required <= set(exclusions):
        groups = pd.DataFrame(columns=["stage", "reason", "count"])
    else:
        groups = (
            exclusions.groupby(["stage", "reason"], dropna=False)
            .size()
            .rename("count")
            .reset_index()
            .sort_values(["stage", "count", "reason"], ascending=[True, False, True])
            .reset_index(drop=True)
        )
    started = pd.to_datetime(manifest.get("started_at"), errors="coerce")
    finished = pd.to_datetime(manifest.get("finished_at"), errors="coerce")
    elapsed = None
    if pd.notna(started) and pd.notna(finished):
        elapsed = max(0.0, (finished - started).total_seconds())
    return {
        "status": str(manifest.get("status", "UNKNOWN")),
        "historical_coverage": float(
            manifest.get(
                "historical_coverage",
                _coverage(
                    manifest.get("valid_history_count"), manifest.get("universe_count")
                ),
            )
        ),
        "quote_coverage": float(
            manifest.get(
                "quote_coverage",
                1.0
                if int(manifest.get("high_rs_count", 0) or 0) == 0
                else _coverage(
                    manifest.get("valid_quote_count"), manifest.get("high_rs_count")
                ),
            )
        ),
        "providers": {
            "Benchmark": str(manifest.get("benchmark_status", "UNKNOWN")),
            "Earnings": str(manifest.get("earnings_status", "UNKNOWN")),
        },
        "started_at": None if pd.isna(started) else started.isoformat(),
        "finished_at": None if pd.isna(finished) else finished.isoformat(),
        "elapsed_seconds": elapsed,
        "market_state": str(manifest.get("market_state", "UNKNOWN")),
        "exclusion_groups": groups,
    }
```

- [ ] **Step 4: Integrate safe feedback and health rendering in `app.py`**

Add imports for `RunStatus`, `INDIA_TZ`, and Task 1/4 helpers. Add:

```python
def refresh_session_prices() -> None:
    clear_startup_price_state(
        st.session_state,
        STARTUP_PRICES_KEY,
        ENRICHED_BUNDLE_KEY,
    )
    st.rerun()


def _render_scan_health(bundle: dict) -> None:
    manifest = bundle["manifest"]
    summary = scan_health_summary(manifest, bundle["exclusions"])
    if summary["status"] == RunStatus.INCOMPLETE.value:
        st.warning("This scan is incomplete. Do not interpret missing matches as no signal.")
    columns = st.columns(2)
    columns[0].metric("Historical coverage", f"{summary['historical_coverage']:.0%}")
    columns[1].metric("High-RS quote coverage", f"{summary['quote_coverage']:.0%}")
    timing = "Duration unavailable"
    if summary["elapsed_seconds"] is not None:
        timing = f"{summary['elapsed_seconds'] / 60:.1f} minutes"
    st.caption(
        f"Started {summary['started_at'] or 'unknown'} · "
        f"Finished {summary['finished_at'] or 'unknown'} · "
        f"Market {summary['market_state']} · {timing}"
    )
    st.subheader("Provider status")
    st.dataframe(
        pd.DataFrame(
            {"Provider": summary["providers"].keys(), "Status": summary["providers"].values()}
        ),
        hide_index=True,
        width="stretch",
    )
    st.subheader("Exclusions by reason")
    if summary["exclusion_groups"].empty:
        st.info("No exclusions were recorded.")
    else:
        st.dataframe(summary["exclusion_groups"], hide_index=True, width="stretch")
    with st.expander("Full run manifest"):
        st.json(manifest)
    with st.expander("All exclusion rows"):
        st.dataframe(bundle["exclusions"], hide_index=True, width="stretch")
```

In `main`, catch `RunBundleError` and call `st.error` with the controlled message
plus `Run Live Scan` recovery guidance. Render scan age near the status badge and
call `st.warning` when `freshness.is_stale`. Add the refresh button after a
screener bundle is available, and replace the raw Scan Health body with
`_render_scan_health(bundle)`.

Wrap `run_scan` in `try/except`. On a returned summary, write this exact session
payload before clearing `_load_run_bundle` and rerunning:

```python
st.session_state["scan_feedback"] = {
    "status": summary.status.value,
    "outcome": summary.outcome,
    "output_path": str(summary.output_path),
}
```

At the next render, pop `scan_feedback`; use `st.success` only for a complete
summary and `st.warning` for `SCAN INCOMPLETE`. If the runner or publisher raises,
call `st.error(f"The scan could not be published: {exc}")` and do not rerun.

- [ ] **Step 5: Run dashboard tests**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q tests/test_app.py
```

Expected: all dashboard tests pass.

- [ ] **Step 6: Commit operational dashboard improvements**

```powershell
rtk git add src/nifty_vcp/dashboard_support.py app.py tests/test_app.py
rtk git commit -m "feat: surface scanner freshness and health"
```

---

### Task 5: Filter Visible Screener Results and Export That View

**Files:**
- Modify: `screener_ui.py`
- Modify: `tests/test_screener_ui.py`
- Modify: `tests/streamlit_screener_fixture.py`

**Interfaces:**
- Produces: `filter_result_view(results, query, state) -> pd.DataFrame`.
- Changes: `_render_results(...) -> pd.DataFrame` returns the visible rows; `render_screen_results_export` receives those visible rows.

- [ ] **Step 1: Write failing pure-filter tests**

Add to `tests/test_screener_ui.py`:

```python
from screener_ui import filter_result_view


def test_result_view_defaults_to_matches_and_searches_symbol_or_company():
    results = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "company_name": ["Alpha Ltd", "Beta Industries", "Gamma Ltd"],
            "state": ["MATCH", "MATCH", "SCAN INCOMPLETE"],
        }
    )

    assert filter_result_view(results, "", "MATCH")["symbol"].tolist() == [
        "AAA",
        "BBB",
    ]
    assert filter_result_view(results, "beta", "MATCH")["symbol"].tolist() == [
        "BBB"
    ]
    assert filter_result_view(results, "CCC", "All states")["symbol"].tolist() == [
        "CCC"
    ]


def test_result_view_handles_missing_company_and_empty_results():
    results = pd.DataFrame({"symbol": ["AAA"], "state": ["NOT ELIGIBLE"]})

    assert filter_result_view(results, "", "MATCH").empty
    assert filter_result_view(results.iloc[0:0], "", "All states").empty
```

- [ ] **Step 2: Run the pure-filter tests and verify import failure**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q tests/test_screener_ui.py -k "result_view"
```

Expected: collection fails because `filter_result_view` is undefined.

- [ ] **Step 3: Implement pure filtering**

Add to `screener_ui.py`:

```python
RESULT_STATES = (
    "MATCH",
    "All states",
    "NO MATCH",
    "NOT ELIGIBLE",
    "SCAN INCOMPLETE",
)


def filter_result_view(
    results: pd.DataFrame,
    query: str,
    state: str,
) -> pd.DataFrame:
    visible = results.copy()
    if visible.empty:
        return visible
    if state != "All states" and "state" in visible:
        visible = visible.loc[visible["state"].astype(str).eq(state)]
    needle = query.strip()
    if needle:
        symbol = visible.get("symbol", pd.Series("", index=visible.index)).astype(str)
        company = visible.get(
            "company_name", pd.Series("", index=visible.index)
        ).astype(str)
        mask = symbol.str.contains(needle, case=False, regex=False) | company.str.contains(
            needle, case=False, regex=False
        )
        visible = visible.loc[mask]
    return visible.copy()
```

- [ ] **Step 4: Add controls and return the visible table**

Change `_render_results` to return a DataFrame. Keep `_result_metrics(results)` before filtering, warn when the unfiltered frame contains `SCAN INCOMPLETE`, render a search input and a state selectbox, then call `filter_result_view`. If the visible frame is empty, show `No rows match these filters.` and return the empty frame. Pass visible rows to selection/evidence logic and return them after rendering.

Update `_render_custom`, `_render_multiple`, and `_render_preset` to retain the visible return value. At the end of `render_screeners`, pass that visible frame to `render_screen_results_export`.
When screeners are unavailable, append
`bundle.get("screeners_unavailable_reason", "Run a new expanded scan.")` to the
existing information message.

- [ ] **Step 5: Extend the fixture and interaction test**

Add a third fixture symbol with `gap_pct=None` and `history_status="SCAN INCOMPLETE"`. Add an AppTest that selects `All states`, confirms the incomplete row appears, searches for `AAA`, and confirms the TradingView code remains `NSE:AAA`.

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q tests/test_screener_ui.py tests/test_watchlist.py
```

Expected: all screener and export tests pass.

- [ ] **Step 6: Commit result-workspace improvements**

```powershell
rtk git add screener_ui.py tests/test_screener_ui.py tests/streamlit_screener_fixture.py
rtk git commit -m "feat: filter visible screener results"
```

---

### Task 6: Documentation, Full Verification, and GitHub Deployment

**Files:**
- Modify: `README.md`
- Verify: all changed source and test files

**Interfaces:**
- Consumes: every prior task.
- Produces: a documented, verified `master` branch pushed to `origin`.

- [ ] **Step 1: Update operating documentation**

In the README Dashboard section, document these exact behaviors:

```markdown
The dashboard labels the age of the persisted daily scan and warns prominently
when it is more than one calendar day old. Newer Yahoo prices do not make stored
daily screener signals current.

Use **Refresh Yahoo prices** to discard only the current browser session's quote
snapshot and fetch it again. This does not run the full scanner or write prices to
disk. Provider or pipeline failures are shown as **SCAN INCOMPLETE**, never as a
zero-signal result.
```

- [ ] **Step 2: Run the complete automated verification**

Run:

```powershell
rtk .\.venv\Scripts\python.exe -m pytest -q
rtk .\.venv\Scripts\python.exe -m ruff check .
rtk git diff --check
```

Expected: all tests pass, Ruff reports `All checks passed!`, and diff check prints no errors.

- [ ] **Step 3: Run a current bounded provider scan**

Run:

```powershell
rtk .\.venv\Scripts\python.exe scan.py --max-symbols 10 --output-dir outputs-smoke-release
```

Expected: the command publishes a timestamped bundle and prints an explicit `COMPLETE` or `SCAN INCOMPLETE` status. If incomplete, confirm its manifest contains coverage or fatal-stage diagnostics and does not say `NO BREAKOUTS`.

- [ ] **Step 4: Run Streamlit and smoke-test rendered flows**

Start the app on an unused 8500-series port, then verify:

```powershell
rtk .\.venv\Scripts\python.exe -m streamlit run app.py --server.headless true --server.port 8502
```

Check `http://localhost:8502/_stcore/health`, then inspect desktop and 390x844 layouts. Verify the stale warning, refresh action, Scan Health summaries, default MATCH view, state/search filters, evidence selection, screen-results export, and TV Top 25 export. Stop the local server after the checks.

- [ ] **Step 5: Review the release diff and commit documentation**

Run:

```powershell
rtk git status --short
rtk git diff --stat HEAD~5..HEAD
rtk git diff -- README.md
rtk git add README.md
rtk git commit -m "docs: explain scanner freshness controls"
```

Expected: only intended source, test, design, plan, and README changes are tracked; diagnostic output directories remain untracked or ignored.

- [ ] **Step 6: Push and verify GitHub**

Run:

```powershell
rtk git push origin master
rtk git status --short --branch
rtk git log -1 --oneline --decorate
```

Expected: push succeeds, local `master` matches `origin/master`, and the final commit is decorated with both refs.
