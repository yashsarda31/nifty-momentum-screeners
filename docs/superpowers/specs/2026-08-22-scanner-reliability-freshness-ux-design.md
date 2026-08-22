# Scanner Reliability, Freshness, and Usability Design

**Date:** 2026-08-22  
**Status:** User-approved direction; written specification pending review  
**Application:** Nifty Momentum Screeners

## Goal

Make the existing scanner safer and easier to operate without adding strategies
or changing signal calculations. The release will make stale results unmistakable,
keep provider and artifact failures from crashing the Streamlit interface, and make
the existing screener results easier to inspect.

## Product Decisions

- Preserve the current selected universe: the top 1,000 NSE equities by
  60-session median traded value plus the existing recent-IPO overlay.
- Preserve every preset screener, custom screener, TradingView export, momentum
  formula, VCP score, and completed-candle rule.
- Continue fetching Yahoo startup prices into `st.session_state` only. Do not add
  a shared, TTL, process, or disk cache for prices.
- Continue distinguishing `COMPLETE`, `NO BREAKOUTS`, `SCAN INCOMPLETE`,
  `NOT ELIGIBLE`, and quote availability states.
- Improve operational reliability and usability before expanding the strategy
  catalog.

## Freshness and Price Refresh

The dashboard will calculate a display-only scan age from the persisted
`finished_at` timestamp. It will show the exact timestamp and a plain-language age.
A scan from today is current, a scan from an earlier date is visibly dated, and a
scan more than one calendar day old receives a prominent stale-results warning.
The warning will state that screener signals still come from the stored completed
daily candles, even when a newer Yahoo price snapshot is displayed.

The sidebar will add a `Refresh Yahoo prices` action. It will remove only the
current session's startup-price snapshot and derived enriched bundle, then rerun
the app. It will not alter the published scan or trigger a full scan. Ordinary
widget reruns will continue reusing the session snapshot, and a browser refresh
will continue starting a fresh session snapshot.

## Scan Failure Handling

The scan pipeline will retain its explicit incomplete-run semantics. Unexpected
failures after universe loading will be converted into a timestamped
`SCAN INCOMPLETE` run with a concise stage and error diagnostic when the publisher
is still usable. Provider failures must never be displayed as `NO BREAKOUTS`.

The Streamlit scan action will inspect the returned summary. A complete run will
show its outcome; an incomplete run will show a warning and diagnostic rather than
implying success. If the pipeline or publisher itself raises, the app will catch
the exception, keep the interface alive, and show recovery guidance. No raw stack
trace will be the primary user-facing result.

## Stored Artifact Handling

Loading `latest.json`, its manifest, or its required tables can currently raise
and stop the whole app. Bundle loading will validate:

- `latest.json` is readable JSON with a non-empty `run_directory`;
- the referenced directory stays inside the configured output root;
- the manifest and required schema-one artifacts exist and are readable;
- schema-two screener files are either all present or clearly unavailable.

The UI will catch a bundle-load failure and show the exact affected run plus a
safe instruction to run a new scan. It will not silently present a partially read
bundle as complete. Existing valid files will not be deleted or rewritten.

## Scan Health Experience

The Scan Health tab will lead with readable coverage and provider summaries rather
than raw JSON. It will show:

- historical and high-RS quote coverage counts and percentages;
- benchmark and earnings-provider status;
- scan start, finish, market state, and elapsed duration when available;
- exclusion counts grouped by stage and reason;
- a clear warning when the run is incomplete.

The full manifest and exclusion table will remain available in expanders for
auditing.

## Screener Results Experience

Preset and multiple-scan result tables will gain controls for symbol/company
search and result state. The default state view will be `MATCH`; users can switch
to all results, `NO MATCH`, `NOT ELIGIBLE`, or `SCAN INCOMPLETE` without
recalculating provider data.

State totals and any incomplete count will remain visible above the filtered table
so the default match view cannot conceal data-quality problems. Evidence drilldown
and the screen-results TradingView export will operate on the visible filtered
results. The export will still include only `MATCH` rows and will never substitute
the independent TV Top 25 list.

## Code Boundaries

- Pure freshness, artifact-validation, filtering, and health-summary helpers will
  be kept separately testable from Streamlit rendering.
- `app.py` will coordinate bundle loading, refresh actions, scan feedback, and
  top-level health/freshness UI.
- `screener_ui.py` will own result search/state controls and pass the visible result
  set to evidence and export rendering.
- `src/nifty_vcp/pipeline.py` will own stage-aware incomplete-run diagnostics.
- Existing financial calculations will not be refactored unless required for a
  regression fix.

## Testing and Verification

Implementation will follow test-first red-green cycles. Regression coverage will
include:

- same-day, dated, malformed, and missing scan timestamps;
- session-only price refresh invalidation without clearing unrelated state;
- post-universe pipeline failure producing `SCAN INCOMPLETE`, never
  `NO BREAKOUTS`;
- corrupt or path-escaping latest pointers producing a controlled load error;
- health summaries for complete, incomplete, and empty diagnostic data;
- search/state filtering and export behavior on the visible result set;
- Streamlit interaction tests for refresh, scan feedback, health, and screener
  controls.

Before GitHub deployment, verification will run the full pytest suite, Ruff, a
bounded current-provider scan, Streamlit startup and health checks, and rendered
desktop and narrow-screen user-flow smoke tests. The final diff will be reviewed
before committing and pushing the configured `master` branch.

## Non-Goals

- New screening strategies, backtests, alerts, order placement, or broker links.
- Replacing Yahoo Finance or presenting it as exchange-grade real-time data.
- Persisting startup quotes or recalculating daily indicators from intraday data.
- Background polling or an automatic full scan.
- Deleting or rewriting existing scan bundles.
