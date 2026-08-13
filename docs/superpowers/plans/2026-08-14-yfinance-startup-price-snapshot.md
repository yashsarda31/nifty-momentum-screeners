# Yfinance Startup Price Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch a fresh yfinance price snapshot once per Streamlit browser session, display it across the scanner, and refresh it when the browser page is manually reloaded.

**Architecture:** Reuse the existing bounded `collect_latest_quotes` adapter and add a small `startup_prices` module that converts quote records into a complete, mergeable table. Keep the snapshot only in `st.session_state`, keyed to the loaded scan directory, then refresh high-RS breakout classification and add display-only price fields to in-memory tables.

**Tech Stack:** Python 3.12, pandas, yfinance, Streamlit, pytest, Streamlit AppTest, Ruff

## Global Constraints

- Do not use `st.cache_data`, a TTL cache, disk cache, or shared process cache.
- Fetch every symbol in the loaded selected universe once per browser session.
- Reuse the same snapshot for widget reruns in that session.
- A manual browser refresh must cause a new request.
- Completed daily candles remain authoritative for technical screeners.
- Only `LIVE` quotes can confirm live breakouts.
- Provider failures must remain visible and must not remove symbols.
- Do not persist startup quotes into timestamped scan artifacts.

---

### Task 1: Validate and Normalize Startup Quotes

**Files:**
- Create: `src/nifty_vcp/startup_prices.py`
- Modify: `src/nifty_vcp/market_data.py`
- Create: `tests/test_startup_prices.py`
- Modify: `tests/test_market_data.py`

**Interfaces:**
- Consumes: `collect_latest_quotes(symbols, now, config) -> tuple[dict[str, QuoteRecord], dict[str, str]]`
- Produces: `StartupPriceSnapshot`, `fetch_startup_prices(universe, now, config, quote_loader)`, and `attach_startup_prices(frame, quote_table, close_column)`

- [ ] **Step 1: Write failing validation and snapshot tests**

Add a market-data test proving that a zero, negative, or infinite latest close becomes `UNAVAILABLE`. Add startup-price tests with two selected symbols, one valid quote and one unavailable quote. Assert that the snapshot table retains both symbols and contains `latest_price`, `quote_timestamp`, `quote_status`, `quote_age_minutes`, and `quote_reason`.

```python
def test_startup_snapshot_retains_unavailable_symbols():
    universe = pd.DataFrame(
        {"symbol": ["AAA", "MISS"], "yahoo_symbol": ["AAA.NS", "MISS.NS"]}
    )
    records = {
        "AAA": QuoteRecord("AAA", 105.0, NOW, QuoteStatus.LIVE, 0.0, ""),
        "MISS": QuoteRecord(
            "MISS", None, None, QuoteStatus.UNAVAILABLE, None, "provider failure"
        ),
    }

    snapshot = fetch_startup_prices(
        universe,
        now=NOW,
        quote_loader=lambda symbols, now, config: (records, {"MISS": "provider failure"}),
    )

    assert snapshot.table["symbol"].tolist() == ["AAA", "MISS"]
    assert snapshot.table.loc[0, "latest_price"] == 105.0
    assert snapshot.table.loc[1, "quote_status"] == "UNAVAILABLE"
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m pytest tests/test_market_data.py tests/test_startup_prices.py -q`

Expected: failure because `nifty_vcp.startup_prices` does not exist and invalid latest prices are not rejected.

- [ ] **Step 3: Reject invalid latest prices in the provider adapter**

After selecting the latest close in `collect_latest_quotes`, validate it before constructing a live record:

```python
price = float(close.iloc[-1])
if not math.isfinite(price) or price <= 0:
    reason = "quote price must be finite and positive"
    quotes[symbol] = QuoteRecord(
        symbol, None, None, QuoteStatus.UNAVAILABLE, None, reason
    )
    exclusions[symbol] = reason
    continue
```

- [ ] **Step 4: Implement the startup-price module**

Create a dataclass carrying the fetch timestamp, quote-record mapping, and quote table. Build exactly one output row per universe symbol and keep unavailable reasons.

```python
@dataclass(frozen=True)
class StartupPriceSnapshot:
    fetched_at: datetime
    quotes: dict[str, QuoteRecord]
    table: pd.DataFrame


def fetch_startup_prices(
    universe: pd.DataFrame,
    now: datetime | None = None,
    config: ScanConfig | None = None,
    quote_loader: Callable = collect_latest_quotes,
) -> StartupPriceSnapshot:
    fetched_at = now or datetime.now(tz=INDIA_TZ)
    quotes, _ = quote_loader(universe, fetched_at, config or ScanConfig())
    rows = []
    for item in universe.itertuples(index=False):
        record = quotes.get(
            item.symbol,
            QuoteRecord(
                item.symbol,
                None,
                None,
                QuoteStatus.UNAVAILABLE,
                None,
                "quote unavailable",
            ),
        )
        rows.append(
            {
                "symbol": item.symbol,
                "latest_price": record.price,
                "quote_timestamp": (
                    record.timestamp.isoformat() if record.timestamp else ""
                ),
                "quote_status": record.status.value,
                "quote_age_minutes": record.age_minutes,
                "quote_reason": record.reason,
            }
        )
    return StartupPriceSnapshot(fetched_at, quotes, pd.DataFrame(rows))
```

Implement `attach_startup_prices` as a left merge after removing older copies of the startup display columns. Calculate `price_change_pct` only when both the startup price and requested completed-close column are finite and positive.

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m pytest tests/test_market_data.py tests/test_startup_prices.py -q`

Expected: all focused tests pass.

```bash
git add src/nifty_vcp/market_data.py src/nifty_vcp/startup_prices.py tests/test_market_data.py tests/test_startup_prices.py
git commit -m "feat: add startup price snapshots"
```

### Task 2: Fetch Once Per Browser Session and Refresh Breakouts

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `fetch_startup_prices(...) -> StartupPriceSnapshot`, `attach_startup_prices(...) -> pd.DataFrame`, and `classify_high_rs_breakouts(...) -> pd.DataFrame`
- Produces: `get_session_startup_prices(session_state, run_key, universe, fetcher) -> StartupPriceSnapshot` and `apply_startup_prices(bundle, snapshot) -> dict`

- [ ] **Step 1: Write failing session-lifetime tests**

Use a plain dictionary as session state and a counting fetcher. Two calls for the same `run_key` must make one provider call. A new empty dictionary must make another call, modelling a browser refresh. A changed `run_key` in the same session must also refetch.

```python
def test_startup_prices_fetch_once_per_session_and_refetch_for_new_session():
    calls = []

    def fetcher(universe):
        calls.append(list(universe["symbol"]))
        return snapshot()

    first_session = {}
    get_session_startup_prices(first_session, "run-1", universe(), fetcher)
    get_session_startup_prices(first_session, "run-1", universe(), fetcher)
    get_session_startup_prices({}, "run-1", universe(), fetcher)

    assert len(calls) == 2
```

Add a bundle-refresh test proving that rankings and screener features retain daily `latest_close`, gain the four startup display fields plus `price_change_pct`, and that only a `LIVE` quote above the pivot appears in `breakouts`.

- [ ] **Step 2: Run the app tests and confirm failure**

Run: `python -m pytest tests/test_app.py -q`

Expected: failure because the session and bundle helper functions do not exist.

- [ ] **Step 3: Implement session-scoped orchestration**

Use a single session key and no Streamlit cache decorator:

```python
STARTUP_PRICES_KEY = "startup_prices"


def get_session_startup_prices(session_state, run_key, universe, fetcher):
    stored = session_state.get(STARTUP_PRICES_KEY)
    if stored is None or stored["run_key"] != run_key:
        stored = {"run_key": run_key, "snapshot": fetcher(universe)}
        session_state[STARTUP_PRICES_KEY] = stored
    return stored["snapshot"]
```

The production caller passes `lambda universe: fetch_startup_prices(universe)`.

- [ ] **Step 4: Apply the snapshot without mutating persisted artifacts**

Copy the loaded bundle, reconstruct each high-RS symbol's completed history from `chart_history`, call `classify_high_rs_breakouts`, and then attach startup display fields to `rankings`, refreshed `setups`, and `features`. Set `breakouts` to only refreshed rows where `is_breakout` is true. Store the snapshot under `startup_prices` for header metrics.

- [ ] **Step 5: Wire startup fetching into `main`**

After `load_latest_run` succeeds and before rendering metrics or tabs:

```python
if bundle.get("screeners_available"):
    snapshot = get_session_startup_prices(
        st.session_state,
        str(bundle["path"]),
        bundle["selected_universe"],
        fetch_startup_prices,
    )
    bundle = apply_startup_prices(bundle, snapshot)
```

Wrap provider execution in the service's partial-failure contract; the UI must remain usable when all quote rows are unavailable.

- [ ] **Step 6: Run app tests and commit**

Run: `python -m pytest tests/test_app.py tests/test_breakouts.py -q`

Expected: all focused tests pass.

```bash
git add app.py tests/test_app.py
git commit -m "feat: refresh prices on app session start"
```

### Task 3: Surface Latest Prices Across Screeners

**Files:**
- Modify: `src/nifty_vcp/screeners.py`
- Modify: `screener_ui.py`
- Modify: `tests/test_screeners.py`
- Modify: `tests/test_screener_ui.py`

**Interfaces:**
- Consumes: startup display columns attached to `bundle["features"]`
- Produces: preset and multi-scan results containing `latest_price`, `price_change_pct`, `quote_status`, and `quote_timestamp`

- [ ] **Step 1: Write failing result-propagation tests**

Extend a feature fixture with startup fields and assert that `evaluate_screener` returns them unchanged. Add a multiple-scan assertion for the same fields. In the UI test, assert the display-column selector includes all four startup fields when present.

```python
assert result.iloc[0]["latest_price"] == 105.0
assert result.iloc[0]["quote_status"] == "LIVE"
assert result.iloc[0]["price_change_pct"] == pytest.approx(5.0)
```

- [ ] **Step 2: Run focused screener tests and confirm failure**

Run: `python -m pytest tests/test_screeners.py tests/test_screener_ui.py -q`

Expected: failure because evaluator output currently drops startup price fields.

- [ ] **Step 3: Pass display-only fields through pure screener evaluation**

Add the following optional fields to result columns and row construction without referencing them in any screening condition:

```python
DISPLAY_QUOTE_FIELDS = (
    "latest_price",
    "price_change_pct",
    "quote_status",
    "quote_timestamp",
)
```

Propagate the same fields from the first matched row in `multiple_scan_matches`.

- [ ] **Step 4: Render price fields and snapshot health**

Add the display quote fields to `_render_results` immediately after `price_date`. In `app.py`, render a caption or compact metric row with snapshot timestamp, usable quote count, selected-symbol count, and an explicit warning when coverage is partial or zero.

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m pytest tests/test_screeners.py tests/test_screener_ui.py tests/test_app.py -q`

Expected: all focused tests pass.

```bash
git add src/nifty_vcp/screeners.py screener_ui.py app.py tests/test_screeners.py tests/test_screener_ui.py tests/test_app.py
git commit -m "feat: show startup quotes in screener results"
```

### Task 4: Document and Verify the Complete Workflow

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-14-yfinance-startup-price-snapshot.md`

**Interfaces:**
- Consumes: completed startup snapshot workflow
- Produces: verified local feature and pushed GitHub commits

- [ ] **Step 1: Document quote lifecycle and limitations**

Update the README to state that the app fetches yfinance one-minute quotes once per browser session, widget reruns reuse session state, a manual browser refresh fetches again, and Yahoo data may be delayed or unavailable.

- [ ] **Step 2: Run targeted and full automated verification**

Run:

```bash
python -m pytest tests/test_market_data.py tests/test_startup_prices.py tests/test_app.py tests/test_screeners.py tests/test_screener_ui.py tests/test_breakouts.py -q
python -m pytest -q
python -m ruff check .
```

Expected: every pytest test passes and Ruff reports no errors.

- [ ] **Step 3: Run a local Streamlit smoke test**

Start Streamlit on an unused localhost port, check `/_stcore/health`, and inspect the initial rendered app for snapshot timestamp, quote coverage, latest-price columns, and unavailable fallback. Do not deploy.

- [ ] **Step 4: Commit final documentation and plan state**

```bash
git add README.md docs/superpowers/plans/2026-08-14-yfinance-startup-price-snapshot.md
git commit -m "docs: explain startup price refresh"
```

- [ ] **Step 5: Push to the configured GitHub remote**

Run: `git push`

Expected: the current branch and all startup-price commits are accepted by the configured GitHub remote.
