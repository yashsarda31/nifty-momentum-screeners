# Nifty Total Market Momentum and VCP Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested Python scanner and local liquid-glass Streamlit dashboard that ranks the official Nifty Total Market universe, detects live 55-session breakouts among RS 80+ stocks, and explains a five-star Minervini-inspired VCP score.

**Architecture:** Keep market-data adapters separate from deterministic analytics. The pipeline downloads and validates the official universe and completed daily OHLCV, ranks valid stocks, scores only RS 80+ setups, adds bounded Yahoo intraday quotes, applies coverage gates, and atomically publishes CSV/JSON artifacts consumed by a read-only Streamlit UI.

**Tech Stack:** Python 3.11+, pandas, numpy, requests, yfinance, Streamlit, Plotly, pytest, Ruff.

## Global Constraints

- Use the official Nifty Total Market constituent CSV: `https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv`.
- Use Yahoo Finance only for personal research data; label it unofficial and potentially delayed.
- Weighted momentum is `40% * 63d + 20% * 126d + 20% * 189d + 20% * 252d` total adjusted returns.
- Map cross-sectional momentum to integer RS ratings from 1 through 99; high RS is `>= 80`.
- A breakout requires the latest valid one-minute price to be strictly above the prior 55 completed-session high.
- Calculate all historical pivots, moving averages, ATR, ranges, and completed-session volume without an unfinished current daily bar.
- Score the five documented VCP stars only for high-RS stocks and expose every component's evidence.
- A run is `SCAN INCOMPLETE` below 90% valid historical coverage or below 90% live-quote coverage among high-RS stocks.
- Never present missing or stale quotes as `NO BREAKOUT`.
- Keep the dashboard local; do not deploy.
- Implement every behavior test-first and preserve red/green evidence in the task transcript.

## File Map

- `pyproject.toml`: package metadata, runtime dependencies, pytest, and Ruff configuration.
- `src/nifty_vcp/__init__.py`: package version only.
- `src/nifty_vcp/models.py`: immutable configuration/result records and status enums.
- `src/nifty_vcp/universe.py`: official constituent download, parsing, and validation.
- `src/nifty_vcp/sessions.py`: India timezone, market-state labeling, and unfinished-bar removal.
- `src/nifty_vcp/market_data.py`: Yahoo daily/intraday adapters, normalization, batching, retries, and validation.
- `src/nifty_vcp/momentum.py`: horizon returns, weighted momentum, and cross-sectional RS rating.
- `src/nifty_vcp/vcp.py`: deterministic five-star calculation and evidence.
- `src/nifty_vcp/breakouts.py`: pivot calculation, quote classification, and breakout result.
- `src/nifty_vcp/storage.py`: atomic CSV/JSON run artifacts and latest pointer.
- `src/nifty_vcp/pipeline.py`: orchestration and coverage/status semantics.
- `scan.py`: command-line scanner entry point.
- `app.py`: Streamlit dashboard entry point.
- `assets/liquid_glass.css`: dashboard visual system.
- `tests/`: one focused test module per analytical/data boundary plus pipeline and UI smoke tests.
- `README.md`: isolated Windows setup, scan, dashboard, methodology, and limitations.

---

### Task 1: Package Skeleton and Domain Models

**Files:**
- Create: `pyproject.toml`
- Create: `src/nifty_vcp/__init__.py`
- Create: `src/nifty_vcp/models.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces: `ScanConfig`, `RunStatus`, `MarketState`, `QuoteStatus`, `QuoteRecord`, `VCPResult`, `BreakoutResult`, and `ScanSummary`.
- Consumes: nothing.

- [ ] **Step 1: Add the environment and a failing model-boundary test**

Create `pyproject.toml` with Python `>=3.11`, package discovery under `src`, runtime dependencies `numpy>=2.0`, `pandas>=2.2`, `requests>=2.32`, `yfinance>=0.2.65`, `streamlit>=1.45`, and `plotly>=6.0`; add optional dev dependencies `pytest>=8.3` and `ruff>=0.12`. Configure pytest with `pythonpath = ["src"]` and Ruff line length 88.

Create `tests/test_models.py`:

```python
import pytest

from nifty_vcp.models import ScanConfig


def test_scan_config_rejects_invalid_thresholds():
    with pytest.raises(ValueError, match="coverage_threshold"):
        ScanConfig(coverage_threshold=1.1)
    with pytest.raises(ValueError, match="high_rs_threshold"):
        ScanConfig(high_rs_threshold=100)


def test_scan_config_defaults_match_approved_design():
    config = ScanConfig()
    assert config.high_rs_threshold == 80
    assert config.pivot_sessions == 55
    assert config.coverage_threshold == 0.90
    assert config.momentum_sessions == (63, 126, 189, 252)
    assert config.momentum_weights == (0.40, 0.20, 0.20, 0.20)
```

- [ ] **Step 2: Create the virtual environment and verify RED**

Run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest tests/test_models.py -v
```

Expected: collection fails because `nifty_vcp.models` does not exist.

- [ ] **Step 3: Implement the minimal typed domain model**

Create enums with exact string values: `RunStatus.COMPLETE = "COMPLETE"`, `RunStatus.INCOMPLETE = "SCAN INCOMPLETE"`; `MarketState.OPEN`, `CLOSED`, `PREOPEN`; and `QuoteStatus.LIVE`, `DELAYED`, `LAST_AVAILABLE`, `UNAVAILABLE`.

Implement frozen dataclasses:

```python
@dataclass(frozen=True)
class ScanConfig:
    high_rs_threshold: int = 80
    pivot_sessions: int = 55
    coverage_threshold: float = 0.90
    momentum_sessions: tuple[int, ...] = (63, 126, 189, 252)
    momentum_weights: tuple[float, ...] = (0.40, 0.20, 0.20, 0.20)
    daily_batch_size: int = 75
    quote_batch_size: int = 40
    request_timeout: float = 20.0
    max_retries: int = 3

    def __post_init__(self) -> None:
        if not 0 < self.coverage_threshold <= 1:
            raise ValueError("coverage_threshold must be in (0, 1]")
        if not 1 <= self.high_rs_threshold <= 99:
            raise ValueError("high_rs_threshold must be in [1, 99]")
        if len(self.momentum_sessions) != len(self.momentum_weights):
            raise ValueError("momentum sessions and weights must align")
        if not math.isclose(sum(self.momentum_weights), 1.0):
            raise ValueError("momentum weights must sum to 1")
```

Define `QuoteRecord(symbol, price, timestamp, status, age_minutes, reason)`, `VCPResult(total_stars: int, components: Mapping[str, bool], evidence: Mapping[str, float | bool | str])`, `BreakoutResult(symbol, live_price, pivot, breakout_pct, is_breakout, quote_status, quote_timestamp)`, and `ScanSummary(status, outcome, universe_count, valid_history_count, high_rs_count, valid_quote_count, breakout_count, started_at, finished_at, output_path)` with validation that counts are nonnegative and stars are in `[0, 5]`.

- [ ] **Step 4: Verify GREEN and commit**

Run `.\.venv\Scripts\python.exe -m pytest tests/test_models.py -v`; expect 2 passed. Run `.\.venv\Scripts\python.exe -m ruff check src tests`; expect exit 0.

Commit:

```powershell
git add pyproject.toml src/nifty_vcp tests/test_models.py
git commit -m "chore: establish scanner domain models"
```

### Task 2: Official Universe and Session Semantics

**Files:**
- Create: `src/nifty_vcp/universe.py`
- Create: `src/nifty_vcp/sessions.py`
- Create: `tests/test_universe.py`
- Create: `tests/test_sessions.py`

**Interfaces:**
- Produces: `parse_universe_csv(content: bytes) -> pd.DataFrame`, `fetch_universe(session, timeout) -> pd.DataFrame`, `market_state(now) -> MarketState`, and `drop_unfinished_daily_bar(frame, now) -> pd.DataFrame`.
- Consumes: `MarketState` from Task 1.

- [ ] **Step 1: Write failing universe tests**

Cover exact column aliases from the official CSV, trimmed symbols, `.NS` Yahoo mapping, duplicate-symbol rejection, non-EQ series removal when a `Series` column exists, and a valid row-count range of 650 through 850. Include a fake response object proving `fetch_universe` sends a browser-like `User-Agent`, calls `raise_for_status`, and passes the configured timeout.

Representative assertion:

```python
frame = parse_universe_csv(
    b"Company Name,Industry,Symbol,Series\nAlpha Ltd,IT, ALPHA ,EQ\n"
    + b"Beta Ltd,Bank,BETA,EQ\n" * 649
)
assert frame.loc[0, "symbol"] == "ALPHA"
assert frame.loc[0, "yahoo_symbol"] == "ALPHA.NS"
```

Build unique symbols in the real test fixture rather than repeating `BETA`.

- [ ] **Step 2: Verify universe tests fail, then implement and pass**

Run `.\.venv\Scripts\python.exe -m pytest tests/test_universe.py -v`; expect import failure. Implement parsing with `pd.read_csv(BytesIO(content))`, normalize header whitespace, require company and symbol columns, keep one row per unique symbol only after rejecting duplicates, and return exactly `symbol`, `company_name`, `industry`, `yahoo_symbol`. Use the approved URL constant and `requests.Session.get`.

Re-run the focused tests; expect all pass.

- [ ] **Step 3: Write failing session tests**

Test Asia/Kolkata datetimes at 09:00, 10:00, 15:29, and 16:00 on a weekday. Test that a daily bar dated today is removed before 15:30, retained at or after 15:30, and that timezone-aware and timezone-naive daily indices normalize correctly without mutating the input.

- [ ] **Step 4: Implement session helpers and verify GREEN**

Use `ZoneInfo("Asia/Kolkata")`; label weekday 09:15–15:30 as `OPEN`, earlier as `PREOPEN`, and later/weekends as `CLOSED`. In `drop_unfinished_daily_bar`, copy, normalize the index to local dates, sort, reject duplicates, and remove today's row only when the market state is `OPEN` or `PREOPEN`.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_universe.py tests/test_sessions.py -v
.\.venv\Scripts\python.exe -m ruff check src tests
```

Expected: all focused tests pass and Ruff exits 0.

- [ ] **Step 5: Commit**

```powershell
git add src/nifty_vcp/universe.py src/nifty_vcp/sessions.py tests/test_universe.py tests/test_sessions.py
git commit -m "feat: load official universe and enforce session boundaries"
```

### Task 3: Yahoo Historical and Intraday Data Adapter

**Files:**
- Create: `src/nifty_vcp/market_data.py`
- Create: `tests/test_market_data.py`

**Interfaces:**
- Produces: `validate_history(frame)`, `split_yahoo_download(raw, tickers)`, `collect_daily_histories(universe, downloader, now, config)`, `collect_latest_quotes(symbols, downloader, now, config)`.
- Consumes: `ScanConfig`, `drop_unfinished_daily_bar`, and universe columns `symbol`, `yahoo_symbol`.

- [ ] **Step 1: Write failing validation and MultiIndex-normalization tests**

Use deterministic frames to require `Open`, `High`, `Low`, `Close`, `Volume`; reject non-increasing/duplicate dates, nonfinite values, nonpositive prices, negative volume, `High < Low`, and fewer than 273 completed sessions. Construct both Yahoo MultiIndex orientations—ticker-first and field-first—and assert both split to identical per-ticker frames.

- [ ] **Step 2: Verify RED, implement validation/splitting, verify GREEN**

Run the focused tests and observe missing functions. Implement numeric coercion, finite checks, OHLC consistency, sorted indexes, and adjusted-history normalization without silently filling missing values. Accept a `minimum_sessions` argument defaulting to 273.

- [ ] **Step 3: Write failing batching, retry, freshness, and quote tests**

Use injected downloader callables; do not patch yfinance internals. Tests must prove:

- Daily symbols are requested in configured bounded batches using `period="15mo"`, `interval="1d"`, `auto_adjust=True`, and `repair=True`.
- A bad batch is retried up to `max_retries`, then split recursively until single bad symbols are isolated.
- The unfinished daily bar is dropped before validation.
- The modal latest date across accepted histories is the freshness reference; older histories move to exclusions with `stale latest bar`.
- Intraday calls use `period="1d"`, `interval="1m"`, `prepost=False`, and select the last finite close per ticker.
- During an open market, quotes older than 15 minutes are `DELAYED`; missing quotes are `UNAVAILABLE`.
- Outside market hours, the last quote is `LAST_AVAILABLE`, never `LIVE`.

- [ ] **Step 4: Implement injected download orchestration and verify GREEN**

Define downloader protocol-compatible call signatures and a production wrapper around `yf.download`. Implement deterministic batch lists, retry delay injection (`sleep: Callable[[float], None]`) so tests use a no-op, exponential delays `1, 2, 4` seconds plus injected jitter, and per-symbol exclusion dictionaries. Return `(histories, exclusions)` and `(quotes, exclusions)` respectively.

Run `.\.venv\Scripts\python.exe -m pytest tests/test_market_data.py -v`; expect all pass.

- [ ] **Step 5: Run the cumulative suite and commit**

Run `.\.venv\Scripts\python.exe -m pytest -q` and Ruff; both must exit 0.

```powershell
git add src/nifty_vcp/market_data.py tests/test_market_data.py
git commit -m "feat: add resilient Yahoo market data adapter"
```

### Task 4: Momentum Components and RS Ratings

**Files:**
- Create: `src/nifty_vcp/momentum.py`
- Create: `tests/test_momentum.py`

**Interfaces:**
- Produces: `calculate_momentum(frame, config) -> dict[str, float]` and `rank_relative_strength(histories, universe, config) -> pd.DataFrame`.
- Consumes: validated completed-session frames and `ScanConfig`.

- [ ] **Step 1: Write failing horizon-return tests**

Create 300-row geometric price series where returns at 63, 126, 189, and 252 sessions are known. Assert each component uses `close.iloc[-1] / close.iloc[-1 - sessions] - 1`, not calendar-day offsets, and assert the exact approved weighted sum. Test insufficient history raises a descriptive `ValueError`.

- [ ] **Step 2: Verify RED, implement calculation, verify GREEN**

Implement with exact output keys `return_63d`, `return_126d`, `return_189d`, `return_252d`, and `weighted_momentum`. Run focused tests; expect pass.

- [ ] **Step 3: Write failing cross-sectional rank tests**

Test monotonic leaders, ties, input-order independence, and a single valid stock. Define rating exactly as:

```python
if count == 1:
    rating = 99
else:
    average_rank = momentum.rank(method="average", ascending=True)
    rating = (1 + 98 * (average_rank - 1) / (count - 1)).round().astype(int)
```

Assert ratings remain in `[1, 99]`, strongest momentum has 99, tied momentum gets tied ratings, and `is_high_rs` is `rs_rating >= config.high_rs_threshold`.

- [ ] **Step 4: Implement ranking, verify all tests, and commit**

Join company metadata by NSE symbol; output deterministic columns and sort by `rs_rating`, then weighted momentum, then symbol descending/descending/ascending. Run focused tests, full pytest, and Ruff.

```powershell
git add src/nifty_vcp/momentum.py tests/test_momentum.py
git commit -m "feat: rank weighted momentum leaders"
```

### Task 5: Transparent Five-Star VCP Engine

**Files:**
- Create: `src/nifty_vcp/vcp.py`
- Create: `tests/test_vcp.py`

**Interfaces:**
- Produces: `score_vcp(frame: pd.DataFrame, pivot_sessions: int = 55) -> VCPResult` and `score_high_rs(histories, rankings, config) -> pd.DataFrame`.
- Consumes: completed validated daily history, `VCPResult`, high-RS rankings.

- [ ] **Step 1: Write one failing test per star**

Use small explicit fixture builders that alter only one condition at a time. Assert exact evidence keys:

- Trend: `close`, `sma50`, `sma150`, `sma200`, `sma200_20d_ago`.
- Range position: `high_252`, `low_252`, `pct_below_high`, `pct_above_low`.
- Contraction: `range_60_pct`, `range_30_pct`, `range_15_pct`.
- Volatility: `atr_50_pct`, `atr_20_pct`, `atr_10_pct`.
- Pivot readiness: `pivot_55`, `distance_to_pivot_pct`, `avg_volume_10`, `avg_volume_50`, `volume_ratio`.

Boundary tests must prove 85%, 30%, 60%, 5%, and 75% pass inclusively, while a one-basis-point miss fails. Assert `total_stars == sum(components.values())`.

- [ ] **Step 2: Verify RED and implement Wilder true range plus each component**

Calculate true range as the row-wise maximum of `high-low`, `abs(high-prev_close)`, and `abs(low-prev_close)`. Calculate `ATR_N` as the simple mean of the latest N true ranges, matching the approved deterministic spec. Use the latest 252 completed rows for range position and the latest 55 completed highs for the pivot.

Return component keys exactly: `trend_template`, `range_position`, `contracting_ranges`, `contracting_volatility`, `pivot_readiness`.

- [ ] **Step 3: Verify GREEN, add high-RS-only orchestration test, and commit**

Test that `score_high_rs` calls `score_vcp` only for rows where `is_high_rs` is true and leaves lower-ranked stocks out of the setup table. Run focused tests, full pytest, and Ruff.

```powershell
git add src/nifty_vcp/vcp.py tests/test_vcp.py
git commit -m "feat: score transparent five-star VCP setups"
```

### Task 6: Live Breakout Classification

**Files:**
- Create: `src/nifty_vcp/breakouts.py`
- Create: `tests/test_breakouts.py`

**Interfaces:**
- Produces: `prior_pivot(frame, sessions=55) -> float`, `classify_breakout(symbol, frame, quote) -> BreakoutResult`, and `classify_high_rs_breakouts(setups, histories, quotes) -> pd.DataFrame`.
- Consumes: completed daily history and normalized quote records from Task 3.

- [ ] **Step 1: Write failing strict-pivot tests**

Prove the pivot uses exactly the latest 55 completed highs. Test prices below and equal to the pivot return false; one tick above returns true; breakout percentage is `(live_price / pivot - 1) * 100`. Test an unavailable/delayed quote cannot be a breakout and preserves its quote status.

- [ ] **Step 2: Verify RED, implement, and verify GREEN**

Raise on fewer than 55 rows, nonfinite quote/pivot, or nonpositive values. Allow `LIVE` quotes to produce `is_breakout`; outside-hours `LAST_AVAILABLE` rows display comparison values but set `is_breakout=False` and a reason `market closed; latest observation only`. A `DELAYED` quote similarly cannot produce a live breakout.

- [ ] **Step 3: Verify cumulative behavior and commit**

Run breakout tests, full pytest, and Ruff.

```powershell
git add src/nifty_vcp/breakouts.py tests/test_breakouts.py
git commit -m "feat: classify strict live 55-session breakouts"
```

### Task 7: Atomic Outputs and End-to-End Pipeline

**Files:**
- Create: `src/nifty_vcp/storage.py`
- Create: `src/nifty_vcp/pipeline.py`
- Create: `tests/test_storage.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `publish_run(output_root, artifacts, manifest) -> Path` and `run_scan(config, dependencies, now) -> ScanSummary`.
- Consumes: all deterministic analytics and injected universe/daily/quote loaders.

- [ ] **Step 1: Write failing atomic-storage tests**

Use pytest `tmp_path`. Assert timestamped output contains `all_rankings.csv`, `high_rs_setups.csv`, `live_breakouts.csv`, `exclusions.csv`, `chart_history.csv.gz`, and `run_manifest.json`; `latest.json` points to the completed directory; a simulated write failure leaves the old `latest.json` unchanged; CSV schemas remain present for empty results.

- [ ] **Step 2: Verify RED, implement temp-directory publication, verify GREEN**

Write artifacts under `<output_root>/.staging-<uuid>`, fsync/close files, rename to `<YYYYMMDD-HHMMSS>`, then write and `os.replace` a temporary latest pointer. On failure, retain staging for diagnosis and never change latest.

- [ ] **Step 3: Write failing pipeline status tests**

Inject fake functions through a `PipelineDependencies` dataclass. Cover:

- `COMPLETE` at exactly 90% historical and quote coverage.
- `SCAN INCOMPLETE` at 89.9% historical coverage.
- `SCAN INCOMPLETE` at 89.9% quote coverage.
- A complete zero-breakout run has outcome `NO BREAKOUTS`.
- An incomplete zero-breakout run has outcome `SCAN INCOMPLETE`, never `NO BREAKOUTS`.
- Universe failure publishes a diagnostic manifest if an output directory is writable.
- Low-RS stocks never enter intraday download requests or VCP scoring.

- [ ] **Step 4: Implement orchestration and verify GREEN**

The manifest must include schema version, source URLs, thresholds, India-local start/finish timestamps, market state, universe count, valid/excluded counts, historical coverage, high-RS count, quote coverage, breakout count, overall status, outcome, and exclusion reason counts. Keep exclusions from universe, history, scoring, and quotes with a `stage` column. Serialize completed OHLCV for high-RS stocks to `chart_history.csv.gz` with `symbol` and `date` columns so dashboard charts never require a second network fetch.

- [ ] **Step 5: Run full quality checks and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scan.py app.py
```

Expect zero failures/errors.

```powershell
git add src/nifty_vcp/storage.py src/nifty_vcp/pipeline.py tests/test_storage.py tests/test_pipeline.py
git commit -m "feat: orchestrate scans with explicit coverage gates"
```

### Task 8: CLI and Liquid-Glass Streamlit Dashboard

**Files:**
- Create: `scan.py`
- Create: `app.py`
- Create: `assets/liquid_glass.css`
- Create: `tests/test_cli.py`
- Create: `tests/test_app.py`

**Interfaces:**
- Produces: CLI options `--output-dir`, `--high-rs`, `--coverage`, `--max-symbols`, and `--now`; Streamlit helpers `load_latest_run`, `render_vcp_stars`, and `build_price_figure`.
- Consumes: `run_scan`, published artifacts, and latest pointer.

- [ ] **Step 1: Write failing CLI contract tests**

Patch only the pipeline boundary. Assert `scan.main(["--max-symbols", "10"])` passes a bounded universe option for smoke testing, prints status/coverage/output path, exits 0 for `COMPLETE`, and exits 2 for `SCAN INCOMPLETE` while still printing the partial-output path.

- [ ] **Step 2: Implement the CLI and verify GREEN**

Use `argparse`; default output is `outputs`; `--now` accepts an ISO timestamp for reproducible diagnostics. Guard with `if __name__ == "__main__": raise SystemExit(main())`.

- [ ] **Step 3: Write failing dashboard helper tests**

Without starting a Streamlit server, test that:

- Missing `latest.json` returns a friendly empty state.
- A manifest and CSV bundle loads with stable dtypes.
- `render_vcp_stars(3)` returns three filled and two empty accessible stars.
- `build_price_figure` contains candlestick, volume, SMA50/150/200, and pivot traces/shapes.
- HTML generated for status badges contains visible text in addition to color.

- [ ] **Step 4: Implement dashboard helpers, CSS, and views**

Use `st.set_page_config(layout="wide")`, load CSS from `assets/liquid_glass.css`, and keep unsafe HTML limited to static app-owned markup. The CSS must define reusable classes for aurora background, glass panels, spectral borders, focus-visible outlines, reduced-motion handling, and mobile stacking.

Implement tabs with exact names: `Live Breakouts`, `RS Leaders`, `All Stocks`, `Scan Health`, and `Methodology`. Use Plotly for the selected-stock chart. The Run button invokes `scan.py` through the pipeline function in-process, shows progress/status, clears cached latest data, and reruns the app. Never accept arbitrary shell input.

- [ ] **Step 5: Verify tests and perform a local server smoke check**

Run unit tests and Ruff. Then start:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.headless true --server.port 8511
```

In a second shell run `curl.exe --fail http://localhost:8511/_stcore/health`; expect `ok`. Stop the server cleanly after the check.

- [ ] **Step 6: Commit**

```powershell
git add scan.py app.py assets/liquid_glass.css tests/test_cli.py tests/test_app.py
git commit -m "feat: add liquid-glass scanner dashboard"
```

### Task 9: Documentation and Live Validation

**Files:**
- Create: `README.md`
- Create: `.gitignore`
- Modify only if live validation exposes a tested defect: relevant `src/` and `tests/` files.

**Interfaces:**
- Produces: reproducible Windows operator instructions and fresh verification evidence.
- Consumes: completed CLI/dashboard.

- [ ] **Step 1: Write operator documentation**

Document exact commands to create/install the isolated environment, run tests, execute a ten-symbol smoke scan, run the full scan, and launch Streamlit. Explain all output files, RS formula, five stars, strict breakout semantics, market-state labels, `NO BREAKOUTS` versus `SCAN INCOMPLETE`, Yahoo personal-use/delay limitations, and that no order execution occurs.

Ignore `.venv/`, `outputs/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, and Streamlit secrets.

- [ ] **Step 2: Run static and automated verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 3: Run a bounded live smoke scan**

Run:

```powershell
.\.venv\Scripts\python.exe scan.py --max-symbols 10 --output-dir outputs-smoke
```

Inspect the manifest and all four CSV schemas. Accept either `COMPLETE` or an accurately explained `SCAN INCOMPLETE`; do not rewrite coverage logic to force success.

- [ ] **Step 4: Run the full official-universe scan**

Run `.\.venv\Scripts\python.exe scan.py --output-dir outputs`. Record universe count, historical coverage, quote coverage, market-state label, and breakout count. If provider throttling prevents 90% coverage after bounded retries, report `SCAN INCOMPLETE` and preserve exclusions; do not claim no breakouts.

- [ ] **Step 5: Verify the dashboard against the real latest run**

Start Streamlit headlessly on port 8511, check `/_stcore/health`, and manually verify that the latest manifest loads, all five tabs render, status/freshness is visible, and selecting a stock produces the expected chart and VCP evidence. Capture any runtime traceback as a failing test before fixing it.

- [ ] **Step 6: Review the final diff and commit**

Run `git status --short`, `git diff --check`, and `git log --oneline`. Confirm only project files are included.

```powershell
git add README.md .gitignore
git commit -m "docs: add scanner operation and validation guide"
```

Do not deploy. Hand off the local dashboard command, output path, verification counts, and any provider-coverage limitation.
