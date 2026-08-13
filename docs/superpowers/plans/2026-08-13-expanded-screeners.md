# Expanded NSE Screener Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fully functional Screeners tab backed by the top 1,000 liquid NSE equities plus every EQ-series IPO listed within two years.

**Architecture:** Extend the existing atomic scan pipeline with an official NSE EQ universe adapter, short-history-aware OHLCV collection, a reusable daily feature matrix, pure preset evaluators, NSE earnings-event enrichment, and local custom-rule persistence. Keep Streamlit UI in a focused `screener_ui.py` module; it reads saved artifacts, applies inexpensive threshold changes locally, and never fetches untracked data.

**Tech Stack:** Python 3.11, pandas, NumPy, requests, yfinance, Streamlit 1.61.1, Plotly, pytest, Streamlit AppTest, Ruff.

## Global Constraints

- Use the official NSE securities-available-for-trading list and include only `EQ` series.
- Select the top 1,000 symbols by 60-session median `Close * Volume` with at least 40 valid observations, then add all stocks listed within the preceding two years.
- Preserve the existing strict live breakout and transparent five-star VCP meanings.
- Permit IPO-specific evaluation from 15 completed sessions; report long-history rules as `NOT ELIGIBLE` rather than dropping the stock.
- Treat missing provider data as `SCAN INCOMPLETE`, never as `NO MATCH`.
- Use completed daily bars for every technical preset; only the existing breakout workflow may say `LIVE`.
- Keep output publication atomic and keep older schema-1 bundles readable.
- Use Streamlit native containers, forms, segmented controls, dataframe selection, stable widget keys, and `width="stretch"`; do not introduce deprecated `use_container_width`.
- Preserve the current liquid-glass visual language and responsive behavior.
- No deployment is included.

## File Map

- Modify `src/nifty_vcp/models.py`: expanded scan configuration and screener-state enum.
- Modify `src/nifty_vcp/universe.py`: NSE EQ parser/fetcher and liquidity-plus-IPO selector.
- Modify `src/nifty_vcp/market_data.py`: accept short histories and collect benchmark data.
- Create `src/nifty_vcp/features.py`: reusable per-symbol technical feature matrix.
- Create `src/nifty_vcp/earnings.py`: official NSE event fetch/normalization.
- Create `src/nifty_vcp/screeners.py`: preset catalogue, default thresholds, and match evaluation.
- Create `src/nifty_vcp/custom_screeners.py`: versioned local AND-rule persistence/evaluation.
- Modify `src/nifty_vcp/pipeline.py`: orchestrate expanded universe, features, events, matches, and artifacts.
- Modify `src/nifty_vcp/storage.py`: no interface change; verify added artifacts remain atomic.
- Create `screener_ui.py`: Streamlit Screeners-tab UI only.
- Modify `app.py`: load optional schema-2 artifacts and add a lazy sixth tab.
- Modify `assets/liquid_glass.css`: narrowly style the new category/result layout.
- Modify `README.md`: expanded coverage, rules, artifacts, and operation notes.
- Create/modify tests under `tests/` alongside each module.

---

### Task 1: Screener domain configuration and states

**Files:**
- Modify: `src/nifty_vcp/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: existing `ScanConfig`.
- Produces: `ScreenerState`, and `ScanConfig(liquidity_count, liquidity_sessions, liquidity_min_observations, recent_ipo_days, minimum_history_sessions)`.

- [ ] **Step 1: Write the failing configuration tests**

Append:

```python
from nifty_vcp.models import ScreenerState


def test_expanded_scan_defaults_and_states():
    config = ScanConfig()
    assert config.liquidity_count == 1_000
    assert config.liquidity_sessions == 60
    assert config.liquidity_min_observations == 40
    assert config.recent_ipo_days == 730
    assert config.minimum_history_sessions == 15
    assert {state.value for state in ScreenerState} == {
        "MATCH", "NO MATCH", "NOT ELIGIBLE", "SCAN INCOMPLETE"
    }


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"liquidity_count": 0}, "liquidity_count"),
        ({"liquidity_min_observations": 61}, "liquidity_min_observations"),
        ({"recent_ipo_days": 0}, "recent_ipo_days"),
        ({"minimum_history_sessions": 14}, "minimum_history_sessions"),
    ],
)
def test_expanded_scan_config_rejects_invalid_values(kwargs, message):
    with pytest.raises(ValueError, match=message):
        ScanConfig(**kwargs)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_models.py -q`

Expected: import or attribute failures for `ScreenerState` and new configuration fields.

- [ ] **Step 3: Add the enum and validated fields**

Add:

```python
class ScreenerState(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO MATCH"
    NOT_ELIGIBLE = "NOT ELIGIBLE"
    INCOMPLETE = "SCAN INCOMPLETE"


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
    max_symbols: int | None = None
    liquidity_count: int = 1_000
    liquidity_sessions: int = 60
    liquidity_min_observations: int = 40
    recent_ipo_days: int = 730
    minimum_history_sessions: int = 15
```

Extend `__post_init__` with explicit positive/range checks, including `liquidity_min_observations <= liquidity_sessions` and `minimum_history_sessions >= 15`.

- [ ] **Step 4: Run focused tests**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_models.py -q`

Expected: all model tests pass.

- [ ] **Step 5: Commit**

```powershell
rtk git add src/nifty_vcp/models.py tests/test_models.py
rtk git commit -m "feat: define expanded screener configuration"
```

### Task 2: Official NSE universe and liquidity-plus-IPO selection

**Files:**
- Modify: `src/nifty_vcp/universe.py`
- Replace tests in: `tests/test_universe.py`

**Interfaces:**
- Consumes: NSE `EQUITY_L.csv`, `histories: dict[str, DataFrame]`, `as_of: datetime`, `ScanConfig`.
- Produces: `fetch_universe(session: requests.Session | None = None, timeout: float = 20.0) -> DataFrame` with `symbol`, `company_name`, `industry`, `series`, `isin`, `listing_date`, `yahoo_symbol`; `select_scan_universe(universe, histories, as_of, config) -> DataFrame` with `median_traded_value_60d`, `liquidity_rank`, `top_1000_liquid`, `recent_ipo_overlay`.

- [ ] **Step 1: Replace universe tests with official schema and selection boundaries**

Use fixtures shaped like:

```python
def equity_csv() -> bytes:
    return (
        "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,ISIN NUMBER\n"
        "OLD,Old Ltd,EQ,01-JAN-2000,INE000A01001\n"
        "IPO,New Ltd,EQ,01-AUG-2026,INE000A01002\n"
        "BESEC,Be Ltd,BE,01-JAN-2020,INE000A01003\n"
    ).encode()


def test_parse_universe_keeps_eq_metadata():
    frame = parse_universe_csv(equity_csv())
    assert list(frame["symbol"]) == ["OLD", "IPO"]
    assert frame.loc[1, "listing_date"] == pd.Timestamp("2026-08-01")
    assert frame.loc[1, "isin"] == "INE000A01002"


def test_selection_adds_recent_ipo_outside_liquidity_cutoff():
    universe = pd.DataFrame({
        "symbol": ["A", "B", "IPO"],
        "listing_date": pd.to_datetime(["2000-01-01", "2001-01-01", "2026-08-01"]),
        "yahoo_symbol": ["A.NS", "B.NS", "IPO.NS"],
        "company_name": ["A", "B", "IPO"],
        "industry": ["", "", ""],
        "series": ["EQ", "EQ", "EQ"],
        "isin": ["1", "2", "3"],
    })
    histories = {
        "A": price_frame(60, close=100, volume=10_000),
        "B": price_frame(60, close=100, volume=9_000),
        "IPO": price_frame(15, close=100, volume=1_000),
    }
    selected = select_scan_universe(
        universe, histories, datetime(2026, 8, 13, tzinfo=TZ),
        ScanConfig(liquidity_count=1),
    ).set_index("symbol")
    assert set(selected.index) == {"A", "IPO"}
    assert bool(selected.loc["A", "top_1000_liquid"])
    assert bool(selected.loc["IPO", "recent_ipo_overlay"])
    assert pd.isna(selected.loc["IPO", "liquidity_rank"])
```

Also cover duplicate symbols, malformed listing dates, fewer than 40 traded-value observations, ties resolved by symbol, and request headers/timeout.

- [ ] **Step 2: Run the tests and confirm old parsing fails**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_universe.py -q`

Expected: failures for NSE column aliases, removed fixed 650–850 count gate, and missing selector.

- [ ] **Step 3: Implement official parsing and selection**

Set:

```python
UNIVERSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
```

Normalize stripped, case-insensitive headers; filter `SERIES == "EQ"`; parse `DATE OF LISTING` with `dayfirst=True`; reject missing/duplicate symbols and unparseable dates; do not impose an index-sized row-count gate.

Implement selection with:

```python
def select_scan_universe(universe, histories, as_of, config):
    cutoff = pd.Timestamp(as_of).tz_localize(None).normalize() - pd.Timedelta(
        days=config.recent_ipo_days
    )
    liquidity = {}
    for symbol, frame in histories.items():
        traded = (frame["Close"] * frame["Volume"]).tail(config.liquidity_sessions)
        valid = traded.replace([np.inf, -np.inf], np.nan).dropna()
        if len(valid) >= config.liquidity_min_observations:
            liquidity[symbol] = float(valid.median())
    ranked = sorted(liquidity, key=lambda s: (-liquidity[s], s))
    rank = {symbol: i + 1 for i, symbol in enumerate(ranked)}
    result = universe.copy()
    result["median_traded_value_60d"] = result["symbol"].map(liquidity)
    result["liquidity_rank"] = result["symbol"].map(rank).astype("Int64")
    result["top_1000_liquid"] = result["liquidity_rank"].le(config.liquidity_count).fillna(False)
    result["recent_ipo_overlay"] = result["listing_date"].ge(cutoff)
    return result[result["top_1000_liquid"] | result["recent_ipo_overlay"]].reset_index(drop=True)
```

- [ ] **Step 4: Run universe tests and lint the file**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_universe.py -q`

Run: `rtk .venv\Scripts\python.exe -m ruff check src/nifty_vcp/universe.py tests/test_universe.py`

Expected: both commands pass.

- [ ] **Step 5: Commit**

```powershell
rtk git add src/nifty_vcp/universe.py tests/test_universe.py
rtk git commit -m "feat: expand scanner to liquid NSE equities and IPOs"
```

### Task 3: Short-history OHLCV and Nifty benchmark collection

**Files:**
- Modify: `src/nifty_vcp/market_data.py`
- Modify: `tests/test_market_data.py`

**Interfaces:**
- Consumes: expanded NSE universe and `ScanConfig.minimum_history_sessions`.
- Produces: `validate_history(frame: pd.DataFrame, minimum_sessions: int = 15) -> None`, the existing `collect_daily_histories` signature retaining short IPO histories, and `collect_benchmark_history(now: datetime, config: ScanConfig, downloader: Callable = yahoo_download) -> pd.DataFrame`.

- [ ] **Step 1: Add failing short-history and benchmark tests**

```python
def test_collect_daily_retains_fifteen_session_ipo():
    universe = pd.DataFrame({"symbol": ["IPO"], "yahoo_symbol": ["IPO.NS"]})
    histories, exclusions = collect_daily_histories(
        universe,
        lambda tickers, **kwargs: price_frame(periods=15),
        datetime(2026, 8, 13, 16, 0, tzinfo=TZ),
        ScanConfig(max_retries=1),
        sleep=lambda _: None,
        jitter=lambda: 0,
    )
    assert list(histories) == ["IPO"]
    assert exclusions == {}


def test_collect_benchmark_requests_nifty_daily_history():
    calls = []
    def downloader(tickers, **kwargs):
        calls.append((tickers, kwargs))
        return price_frame(periods=280)
    result = collect_benchmark_history(
        datetime(2026, 8, 13, 16, 0, tzinfo=TZ), ScanConfig(), downloader
    )
    assert len(result) == 280
    assert calls[0][0] == ["^NSEI"]
    assert calls[0][1]["period"] == "2y"
```

Update the existing bad-history parameterization so fewer than 15, not fewer than 273, fails structural collection validation.

- [ ] **Step 2: Confirm the new tests fail**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_market_data.py -q`

Expected: short IPO rejected and benchmark function missing.

- [ ] **Step 3: Implement the minimum-history split**

Change the daily request to `period="2y"`. Call `validate_history(completed, config.minimum_history_sessions)` inside daily collection. Keep long-history enforcement inside momentum and VCP functions. Add a benchmark loader that uses the same drop-unfinished-bar and structural validation path but requires 253 sessions for RS-line eligibility.

- [ ] **Step 4: Run focused regression tests**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_market_data.py tests/test_momentum.py tests/test_vcp.py -q`

Expected: all tests pass; existing momentum/VCP insufficient-history behavior remains intact.

- [ ] **Step 5: Commit**

```powershell
rtk git add src/nifty_vcp/market_data.py tests/test_market_data.py
rtk git commit -m "feat: retain short IPO histories and Nifty benchmark"
```

### Task 4: Reusable feature matrix and technical pattern evidence

**Files:**
- Create: `src/nifty_vcp/features.py`
- Create: `tests/test_features.py`

**Interfaces:**
- Consumes: `histories`, selected universe, benchmark history, and optional existing rankings/VCP setups.
- Produces: `build_feature_matrix(histories, universe, benchmark, rankings, setups, as_of) -> DataFrame`; `history_evidence(histories) -> DataFrame` for rolling-window fields that do not fit one scalar row.

- [ ] **Step 1: Create deterministic feature fixtures and failing tests**

Create helpers that return OHLCV frames for trend, NR7, tight closes, horizontal resistance, IPO base/momentum/breakout, volume surge/dry-up, flag/pennant, gaps, daily/double/weekly inside bars, and RS-line high.

Representative assertions:

```python
def test_feature_matrix_marks_short_ipo_eligible_without_long_history():
    history = make_ipo_breakout_history(periods=25)
    features = build_feature_matrix(
        {"IPO": history}, ipo_universe(), pd.DataFrame(),
        pd.DataFrame(), pd.DataFrame(), pd.Timestamp("2026-08-13")
    ).set_index("symbol")
    row = features.loc["IPO"]
    assert row["history_sessions"] == 25
    assert bool(row["ipo_breakout"])
    assert pd.isna(row["return_252d"])
    assert row["momentum_eligibility"] == "NOT ELIGIBLE"


def test_pattern_boundaries_are_inclusive():
    matrix = build_feature_matrix(
        boundary_histories(), boundary_universe(), benchmark_frame(),
        pd.DataFrame(), pd.DataFrame(), pd.Timestamp("2026-08-13")
    ).set_index("symbol")
    assert bool(matrix.loc["NR7", "nr7"])
    assert matrix.loc["TIGHT", "three_close_band_pct"] == pytest.approx(1.5)
    assert matrix.loc["GAP", "gap_pct"] == pytest.approx(3.0)
    assert bool(matrix.loc["INSIDE", "daily_inside_bar"])


def test_rs_line_high_requires_aligned_253_sessions():
    row = build_feature_matrix(
        {"RS": rs_leader_history()}, one_stock_universe("RS"),
        benchmark_frame(), pd.DataFrame(), pd.DataFrame(),
        pd.Timestamp("2026-08-13")
    ).iloc[0]
    assert bool(row["rs_high_before_price_high"])
    assert row["rs_line_eligibility"] == "ELIGIBLE"
```

Add separate assertions for all evidence columns named in the design: resistance price/touches/dispersion/distance; ATR ratios; pole gain/depth/length/volume contraction; volume ratios; gap finish; inside-bar flags; moving averages; returns; IPO age and base depth.

- [ ] **Step 2: Run the file and confirm the module is missing**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_features.py -q`

Expected: import failure for `nifty_vcp.features`.

- [ ] **Step 3: Implement small pure helpers**

Create private helpers with exact signatures and responsibilities: `_true_range(frame: pd.DataFrame) -> pd.Series` computes the maximum of high-low and the two prior-close gaps; `_swing_resistance(frame: pd.DataFrame, sessions: int = 60) -> dict` identifies highs above two neighbours on each side and clusters touches within 2%; `_weekly_inside(frame: pd.DataFrame) -> bool | pd.NA` resamples completed Monday-Friday weeks and compares the last two; `_flag_pennant(frame: pd.DataFrame) -> dict` searches 10–30-session poles followed by 5–20-session consolidations; `_rs_line_features(frame: pd.DataFrame, benchmark: pd.DataFrame) -> dict` inner-aligns closes and compares the latest stock/benchmark ratio and stock close with their prior 252-session highs; `_one_symbol_features(symbol: str, frame: pd.DataFrame, metadata: pd.Series, benchmark: pd.DataFrame, as_of: pd.Timestamp) -> dict` combines those helpers with moving averages, returns, ATR, volume, gap, IPO, and inside-bar evidence.

Use `pd.NA` and explicit eligibility strings when a field cannot be computed. Never fill missing numeric evidence with zero. Reuse ranking and setup columns by left-merging on `symbol`.

- [ ] **Step 4: Implement the public matrix builders**

```python
def build_feature_matrix(histories, universe, benchmark, rankings, setups, as_of):
    metadata = universe.set_index("symbol")
    rows = [
        _one_symbol_features(symbol, frame, metadata.loc[symbol], benchmark, as_of)
        for symbol, frame in histories.items()
        if symbol in metadata.index
    ]
    result = pd.DataFrame(rows)
    for extra in (rankings, setups):
        if not extra.empty:
            result = result.merge(extra, on="symbol", how="left", suffixes=("", "_legacy"))
    return result.sort_values("symbol", ignore_index=True)
```

`history_evidence` stores one record per symbol/session with only `symbol`, `date`, OHLCV, and precomputed weekly identifier; it must not duplicate raw histories in memory beyond publication.

- [ ] **Step 5: Run feature tests and Ruff**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_features.py -q`

Run: `rtk .venv\Scripts\python.exe -m ruff check src/nifty_vcp/features.py tests/test_features.py`

Expected: all feature tests and lint pass.

- [ ] **Step 6: Commit**

```powershell
rtk git add src/nifty_vcp/features.py tests/test_features.py
rtk git commit -m "feat: calculate auditable screener features"
```

### Task 5: Official NSE earnings-event adapter

**Files:**
- Create: `src/nifty_vcp/earnings.py`
- Create: `tests/test_earnings.py`

**Interfaces:**
- Consumes: NSE JSON responses for board meetings and financial results, `from_date`, `to_date`, and selected symbols.
- Produces: `fetch_earnings_events(symbols, as_of, timeout=20, session=None) -> tuple[DataFrame, str]`; normalized columns `symbol`, `event_type`, `event_date`, `broadcast_at`, `source_url`; status is `COMPLETE` or `SCAN INCOMPLETE`.

- [ ] **Step 1: Add parser and failure-semantics tests**

```python
def test_parse_board_meetings_keeps_financial_results_only():
    rows = [
        {"symbol": "AAA", "purpose": "Financial Results", "bm_date": "20-Aug-2026"},
        {"symbol": "BBB", "purpose": "Dividend", "bm_date": "21-Aug-2026"},
    ]
    result = parse_board_meetings(rows, SOURCE_URL)
    assert result[["symbol", "event_type"]].to_dict("records") == [
        {"symbol": "AAA", "event_type": "RESULTS_DUE"}
    ]


def test_parse_financial_results_normalizes_broadcast_time():
    result = parse_financial_results([
        {"symbol": "AAA", "broadcastDateTime": "12-Aug-2026 18:30:00"}
    ], SOURCE_URL)
    assert result.iloc[0]["event_type"] == "RESULT_FILED"
    assert result.iloc[0]["broadcast_at"].tzinfo is not None


def test_fetch_failure_returns_empty_frame_and_incomplete_status():
    events, status = fetch_earnings_events(
        {"AAA"}, pd.Timestamp("2026-08-13", tz="Asia/Kolkata"),
        session=FailingSession()
    )
    assert events.empty
    assert status == "SCAN INCOMPLETE"
```

- [ ] **Step 2: Confirm the module is missing**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_earnings.py -q`

Expected: import failure.

- [ ] **Step 3: Implement NSE session bootstrap and bounded endpoints**

Use an NSE browser user-agent, visit `https://www.nseindia.com/` once to obtain cookies, then request the official board-meeting and financial-result JSON endpoints with bounded date ranges. Put endpoint construction in `_board_meeting_url(as_of)` and `_financial_results_url(as_of)` so fixtures can verify exact parameters without network calls. Filter to the selected symbol set after normalization.

Catch request, JSON, and schema exceptions only at `fetch_earnings_events`; return the stable empty schema and `SCAN INCOMPLETE`. Do not turn provider failure into an empty but complete event calendar.

- [ ] **Step 4: Run adapter tests**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_earnings.py -q`

Expected: parser, headers, date ranges, symbol filtering, and incomplete-state tests pass.

- [ ] **Step 5: Commit**

```powershell
rtk git add src/nifty_vcp/earnings.py tests/test_earnings.py
rtk git commit -m "feat: collect official NSE earnings events"
```

### Task 6: Preset catalogue, adjustable thresholds, and multiple-scan matches

**Files:**
- Create: `src/nifty_vcp/screeners.py`
- Create: `tests/test_screeners.py`

**Interfaces:**
- Consumes: feature matrix, earnings events, and threshold overrides.
- Produces: `SCREENER_CATALOG`, `default_thresholds(slug: str) -> dict`, `evaluate_screener(slug: str, features: pd.DataFrame, events: pd.DataFrame, thresholds: Mapping) -> pd.DataFrame`, `evaluate_all_screeners(features: pd.DataFrame, events: pd.DataFrame, overrides: Mapping[str, Mapping] | None = None) -> pd.DataFrame`, and `multiple_scan_matches(matches: pd.DataFrame, selected_slugs: Sequence[str], minimum_count: int) -> pd.DataFrame`.

- [ ] **Step 1: Write catalogue-completeness and result-state tests**

```python
EXPECTED = {
    "horizontal_resistance", "nr7", "three_tight_closes", "atr_contraction",
    "ipo_base", "ipo_momentum", "ipo_breakout", "rs_high_before_price_high",
    "momentum", "relative_volume_surge", "accumulation_day", "volume_dry_up",
    "vcp", "flags_pennants", "results_due", "fresh_results",
    "post_results_gap_up", "gap_up", "gap_down", "gap_and_hold",
    "daily_inside_bar", "double_inside_bar", "weekly_inside_bar",
}


def test_catalogue_contains_every_approved_preset():
    assert set(SCREENER_CATALOG) == EXPECTED


def test_missing_required_feature_is_not_a_negative_result():
    features = pd.DataFrame({"symbol": ["IPO"], "history_sessions": [20]})
    result = evaluate_screener("vcp", features, pd.DataFrame(), {})
    assert result.iloc[0]["state"] == "NOT ELIGIBLE"


def test_adjustable_gap_threshold_changes_match():
    features = pd.DataFrame({"symbol": ["AAA"], "gap_pct": [3.5]})
    assert evaluate_screener("gap_up", features, pd.DataFrame(), {}).iloc[0]["state"] == "MATCH"
    assert evaluate_screener(
        "gap_up", features, pd.DataFrame(), {"minimum_gap_pct": 4.0}
    ).iloc[0]["state"] == "NO MATCH"


def test_multiple_scans_lists_reasons_and_count():
    result = multiple_scan_matches(match_fixture(), ["nr7", "gap_up"], 2)
    assert result.iloc[0]["match_count"] == 2
    assert result.iloc[0]["matched_screeners"] == "NR7 | Gap up"
```

Add one boundary test per catalogue slug, including earnings-source incomplete behavior and VCP 0–5 bounds.

- [ ] **Step 2: Run and confirm the module is missing**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_screeners.py -q`

Expected: import failure.

- [ ] **Step 3: Define immutable catalogue metadata and defaults**

Use a frozen dataclass:

```python
@dataclass(frozen=True)
class ScreenerDefinition:
    slug: str
    category: str
    label: str
    description: str
    minimum_sessions: int
    threshold_defaults: Mapping[str, float | int | bool]
```

The catalogue order must match the reference image. Each evaluator returns one row per input symbol with `screener`, `state`, `reason`, and evidence values; matching rows can later be filtered without losing ineligible diagnostics.

- [ ] **Step 4: Implement preset evaluators and earnings alignment**

Create an `_EVALUATORS` mapping from slug to pure vectorized function. Use inclusive comparisons at documented boundaries. For earnings gaps, align a filing broadcast after market close to the next completed trading session present in the stock history evidence; require both matching NSE event and gap/volume thresholds.

- [ ] **Step 5: Run screener tests and lint**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_screeners.py -q`

Run: `rtk .venv\Scripts\python.exe -m ruff check src/nifty_vcp/screeners.py tests/test_screeners.py`

Expected: all catalogue and boundary tests pass.

- [ ] **Step 6: Commit**

```powershell
rtk git add src/nifty_vcp/screeners.py tests/test_screeners.py
rtk git commit -m "feat: evaluate technical and earnings screeners"
```

### Task 7: Versioned local custom screener rules

**Files:**
- Create: `src/nifty_vcp/custom_screeners.py`
- Create: `tests/test_custom_screeners.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: feature matrix and JSON path.
- Produces: `Rule`, `CustomScreener`, `load_store(path)`, `save_screener(path, screener, overwrite=False)`, `rename_screener(path, old, new)`, `delete_screener(path, name)`, `evaluate_custom(screener, features) -> DataFrame`.

- [ ] **Step 1: Add persistence, validation, and AND-semantics tests**

```python
def test_custom_screener_round_trip_and_and_semantics(tmp_path):
    path = tmp_path / "custom_screeners.json"
    screener = CustomScreener("Strong and liquid", (
        Rule("rs_rating", ">=", 80), Rule("volume_ratio_20d", ">=", 1.5)
    ))
    save_screener(path, screener)
    loaded = load_store(path)["Strong and liquid"]
    result = evaluate_custom(loaded, pd.DataFrame({
        "symbol": ["PASS", "FAIL"], "rs_rating": [90, 90],
        "volume_ratio_20d": [2.0, 1.0],
    }))
    assert list(result.loc[result["state"] == "MATCH", "symbol"]) == ["PASS"]


def test_unknown_field_survives_load_but_evaluates_ineligible(tmp_path):
    path = write_raw_store(tmp_path, field="retired_field")
    loaded = load_store(path)["Legacy"]
    result = evaluate_custom(loaded, pd.DataFrame({"symbol": ["AAA"]}))
    assert result.iloc[0]["state"] == "NOT ELIGIBLE"
    assert "retired_field" in result.iloc[0]["reason"]
```

Also test invalid operators, empty names/rules, duplicate save without overwrite, atomic JSON replacement, rename collision, and delete.

- [ ] **Step 2: Confirm the module is missing**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_custom_screeners.py -q`

Expected: import failure.

- [ ] **Step 3: Implement schema and atomic persistence**

Store:

```json
{
  "schema_version": 1,
  "screeners": {
    "Strong and liquid": {
      "rules": [
        {"field": "rs_rating", "operator": ">=", "value": 80},
        {"field": "volume_ratio_20d", "operator": ">=", "value": 1.5}
      ]
    }
  }
}
```

Allow only `>`, `>=`, `<`, `<=`, `==`, `!=`; compare numeric fields after finite-number validation and categorical fields as exact strings. Write to a sibling temporary file, flush/fsync, and `os.replace` it.

- [ ] **Step 4: Ignore only the local store**

Append `/custom_screeners.json` to `.gitignore`. Do not ignore general JSON files.

- [ ] **Step 5: Run focused tests**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_custom_screeners.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
rtk git add .gitignore src/nifty_vcp/custom_screeners.py tests/test_custom_screeners.py
rtk git commit -m "feat: save and evaluate custom screeners"
```

### Task 8: Pipeline schema 2 and atomic screener artifacts

**Files:**
- Modify: `src/nifty_vcp/pipeline.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Consumes: Tasks 2–7 public interfaces.
- Produces: schema-2 bundle containing `selected_universe.csv`, `screener_features.csv`, `screener_matches.csv`, `earnings_events.csv`, and selected-universe `chart_history.csv.gz`, plus all existing artifacts.

- [ ] **Step 1: Rewrite dependency fixture for expanded stages**

Extend `PipelineDependencies` with:

```python
benchmark_loader: Callable
universe_selector: Callable
feature_builder: Callable
earnings_loader: Callable
screener_runner: Callable
```

Add assertions:

```python
def test_pipeline_publishes_schema_two_screener_bundle(tmp_path):
    deps, published = make_expanded_dependencies()
    run_scan(ScanConfig(), deps, NOW, tmp_path)
    assert published["manifest"]["schema_version"] == 2
    assert {
        "selected_universe.csv", "screener_features.csv",
        "screener_matches.csv", "earnings_events.csv"
    } <= set(published["artifacts"])
    assert published["manifest"]["source_universe_count"] == 3
    assert published["manifest"]["recent_ipo_additions"] == 1


def test_earnings_failure_only_marks_earnings_screeners_incomplete(tmp_path):
    deps, published = make_expanded_dependencies(earnings_status="SCAN INCOMPLETE")
    run_scan(ScanConfig(), deps, NOW, tmp_path)
    matches = published["artifacts"]["screener_matches.csv"]
    assert set(matches.loc[matches["screener"] == "results_due", "state"]) == {"SCAN INCOMPLETE"}
    assert "MATCH" in set(matches.loc[matches["screener"] == "nr7", "state"])
```

Update the prior chart-history test: schema 2 stores every selected symbol, while quote and VCP calls remain limited to mature high-RS symbols.

- [ ] **Step 2: Confirm pipeline tests fail against old dependencies**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_pipeline.py tests/test_storage.py -q`

Expected: dependency signature and artifact assertions fail.

- [ ] **Step 3: Refactor pipeline stages without changing publication guarantees**

Order:

```text
fetch all EQ -> download histories -> select top 1000 + IPO overlay
-> mature-only momentum ranking -> high-RS VCP -> high-RS quotes/breakouts
-> Nifty benchmark -> feature matrix -> NSE events -> all preset matches
-> manifest schema 2 -> one atomic publish_run call
```

If universe or daily price collection fails its 90% gate, publish diagnostics and mark all screeners incomplete. If the benchmark fails, mark only RS-line-dependent results incomplete. If events fail, mark only earnings results incomplete. Continue using the existing complete/no-breakout logic solely for live breakouts.

- [ ] **Step 4: Expand manifest and empty artifacts**

Include source/final counts, selection formulas, recent IPO count, benchmark coverage, feature eligibility counts, per-screener state counts, earnings status, threshold defaults, and grouped exclusions. Ensure stable empty CSV schemas are Arrow-safe strings/nullable numerics.

- [ ] **Step 5: Run pipeline/storage and full domain tests**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_pipeline.py tests/test_storage.py -q`

Run: `rtk .venv\Scripts\python.exe -m pytest tests -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
rtk git add src/nifty_vcp/pipeline.py tests/test_pipeline.py tests/test_storage.py
rtk git commit -m "feat: publish expanded screener scan bundles"
```

### Task 9: Streamlit Screeners tab and old-bundle fallback

**Files:**
- Create: `screener_ui.py`
- Modify: `app.py`
- Modify: `assets/liquid_glass.css`
- Modify: `tests/test_app.py`
- Create: `tests/test_screener_ui.py`

**Interfaces:**
- Consumes: bundle keys `selected_universe`, `features`, `matches`, `earnings`, `chart_history`, manifest, and `custom_screeners.json`.
- Produces: `render_screeners(bundle: dict, custom_store_path: Path = Path("custom_screeners.json")) -> None`; `filter_preset_results(slug: str, features: pd.DataFrame, events: pd.DataFrame, thresholds: Mapping) -> pd.DataFrame`; `selected_result_symbol(event: Mapping, frame: pd.DataFrame) -> str | None`.

- [ ] **Step 1: Extend loader tests for schema 1 and schema 2**

```python
def test_schema_one_bundle_loads_with_screeners_unavailable(tmp_path):
    write_schema_one_bundle(tmp_path)
    bundle = load_latest_run(tmp_path)
    assert bundle["screeners_available"] is False


def test_schema_two_bundle_loads_screener_tables(tmp_path):
    write_schema_two_bundle(tmp_path)
    bundle = load_latest_run(tmp_path)
    assert bundle["screeners_available"] is True
    assert bundle["features"].iloc[0]["symbol"] == "AAA"
```

- [ ] **Step 2: Add AppTest coverage for categories, controls, and old output**

Create a small `tests/streamlit_screener_fixture.py` that imports `render_screeners` and supplies a deterministic in-memory bundle. Test:

```python
def test_all_reference_categories_render():
    at = AppTest.from_file("tests/streamlit_screener_fixture.py").run()
    labels = {button.label for button in at.button}
    assert {"Create/load screener", "Multiple scans", "Horizontal resistance",
            "Tight setup", "IPO scanner", "RS high before price high",
            "Momentum scanner", "Volume screeners", "VCP", "Flags & pennants",
            "Earnings screeners", "Gap screeners", "Inside bar"} <= labels


def test_threshold_widget_filters_stored_results():
    at = AppTest.from_file("tests/streamlit_screener_fixture.py").run()
    at.button(key="screen_gap_screeners").click().run()
    at.selectbox(key="screener_preset").select("Gap up").run()
    at.number_input(key="threshold_minimum_gap_pct").set_value(4.0).run()
    assert "1 match" in [metric.value for metric in at.metric]
```

Add fixture variants for old-bundle messaging, earnings incomplete, no matches, and selected-row detail.

- [ ] **Step 3: Confirm UI tests fail**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_screener_ui.py -q`

Expected: loader keys and `screener_ui` are missing.

- [ ] **Step 4: Implement the UI with stable native widgets**

In `screener_ui.py`:

- initialize `selected_screener_category` and `selected_screener_slug` once with `setdefault`;
- render category buttons in the screenshot order using Material Symbols where useful;
- use a proportional two-column layout on desktop; CSS media query stacks it under 800px;
- use `st.selectbox` for category sub-screeners, `st.form` for related thresholds, `st.multiselect` for Multiple Scans, and `st.data_editor` only for custom rule entry;
- apply filters after form submission without network access;
- display status/match/eligibility metrics in responsive horizontal containers;
- render results with `st.dataframe(display_frame, key="screener_results", on_select="rerun", selection_mode="single-row", hide_index=True, width="stretch", column_config=result_column_config())`;
- pass the selected symbol to a stock-detail helper that reuses `build_price_figure` and evidence display.

In `app.py`, read optional schema-2 files only if all exist, add `Screeners` as tab six, call `st.tabs(["Live breakouts", "RS leaders", "All stocks", "Scan health", "Methodology", "Screeners"], key="main_tabs", on_change="rerun")`, and guard each tab body with `.open`. Cache `load_latest_run` with a bounded cache keyed by the latest pointer modification time, and clear it after a live scan.

- [ ] **Step 5: Add narrow CSS hooks only**

Add classes for `.screener-shell`, `.screener-menu`, and `.screener-results`; keep current colors/tokens. Under `@media (max-width: 800px)`, switch the shell to one column. Do not target generated Streamlit class names.

- [ ] **Step 6: Run Streamlit tests and lint**

Run: `rtk .venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_screener_ui.py -q`

Run: `rtk .venv\Scripts\python.exe -m ruff check app.py screener_ui.py tests/test_app.py tests/test_screener_ui.py`

Expected: loader, interaction, fallback, and lint checks pass.

- [ ] **Step 7: Commit**

```powershell
rtk git add app.py screener_ui.py assets/liquid_glass.css tests/test_app.py tests/test_screener_ui.py tests/streamlit_screener_fixture.py
rtk git commit -m "feat: add interactive Streamlit screener tab"
```

### Task 10: Documentation, live smoke validation, and rendered UI verification

**Files:**
- Modify: `README.md`
- Modify: `scan.py` only if CLI help requires new universe wording.
- Modify: tests only when a reproducible validation defect is found.

**Interfaces:**
- Consumes: completed schema-2 implementation.
- Produces: operator documentation and evidence that tests, data collection, app health, and rendered UI work.

- [ ] **Step 1: Update operational documentation**

Document:

- NSE EQ source and top-1,000-plus-two-year-IPO formula;
- short-history IPO eligibility versus long-history `NOT ELIGIBLE`;
- each category and default threshold;
- NSE earnings-event provenance and incomplete behavior;
- schema-2 artifacts and custom store path;
- expected full-scan runtime/provider constraints;
- explicit research-only limitation.

- [ ] **Step 2: Run the complete deterministic suite and Ruff**

Run: `rtk .venv\Scripts\python.exe -m pytest -q`

Run: `rtk .venv\Scripts\python.exe -m ruff check .`

Expected: zero failures and zero lint errors. Record the final test count.

- [ ] **Step 3: Run a bounded live scan**

Run: `rtk .venv\Scripts\python.exe scan.py --max-symbols 25 --output-dir outputs-smoke`

Expected: a schema-2 timestamped bundle with all nine CSV/GZIP/JSON artifacts, no traceback, and explicit incomplete diagnostics if provider coverage is below 90%. Inspect `run_manifest.json` and confirm recent IPOs are retained when present in the bounded input.

- [ ] **Step 4: Run the full live scan**

Run: `rtk .venv\Scripts\python.exe scan.py --output-dir outputs`

Expected: source-universe count equals the downloaded EQ rows; selected count equals the union of liquidity ranks 1–1,000 and recent IPOs; artifact counts are internally consistent; and no missing value is coerced to zero. A provider-limited run may be `SCAN INCOMPLETE`, but must retain diagnostics and must not claim no matches.

- [ ] **Step 5: Start Streamlit headlessly and probe health**

Run in a persistent terminal:

```powershell
rtk .venv\Scripts\python.exe -m streamlit run app.py --server.headless true --server.port 8511
```

Probe: `rtk proxy powershell -NoProfile -Command "(Invoke-WebRequest -UseBasicParsing http://localhost:8511/_stcore/health).Content"`

Expected: `ok`.

- [ ] **Step 6: Inspect the rendered desktop and narrow layouts**

Open `http://localhost:8511`, verify all six tabs, select every screener category, adjust at least one threshold, select a result row, exercise Multiple Scans, and save/load/rename/delete a disposable custom rule. Repeat the Screeners tab at approximately 390px width and confirm the menu stacks above results without horizontal clipping. Capture any runtime error as a failing AppTest or unit test before fixing it.

- [ ] **Step 7: Re-run final verification after any live defect fix**

Run: `rtk .venv\Scripts\python.exe -m pytest -q`

Run: `rtk .venv\Scripts\python.exe -m ruff check .`

Expected: both pass, and `git status --short` lists only intentional source/docs changes plus generated output paths already ignored by Git.

- [ ] **Step 8: Commit documentation and verification fixes**

```powershell
rtk git add README.md scan.py tests src app.py screener_ui.py assets/liquid_glass.css
rtk git commit -m "docs: document and verify expanded screeners"
```

## Final Acceptance Checklist

- [ ] Every reference-image category runs a real preset or custom-rule calculation.
- [ ] Universe selection is top 1,000 by the documented 60-session liquidity measure plus all two-year NSE EQ IPOs.
- [ ] Short IPOs remain present and show rule-specific eligibility.
- [ ] Every match includes evidence, timestamp, and source status.
- [ ] Earnings and benchmark provider failures affect only dependent screens.
- [ ] Existing live breakout and VCP behavior is unchanged.
- [ ] Schema-1 bundles still load with a clear rescan prompt.
- [ ] Full pytest, Ruff, live smoke scan, full scan, Streamlit health, desktop UI, and narrow UI checks are complete.
