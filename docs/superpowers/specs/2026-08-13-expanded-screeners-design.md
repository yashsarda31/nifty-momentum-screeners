# Expanded NSE Screener Suite Design

**Date:** 2026-08-13  
**Status:** Approved for specification  
**Application:** Nifty Total Market Momentum + VCP Scanner

## Goal

Add a separate, fully functional **Screeners** tab to the local Streamlit app.
The tab will provide the named technical and event screeners shown in the user's
reference image, with visible adjustable thresholds and auditable match reasons.
Expand coverage beyond the Nifty Total Market so recent IPOs and liquid non-index
stocks are not silently omitted.

This remains a local research tool. It will not place orders or claim to reproduce
any proprietary screener's undisclosed formula.

## Universe

The official NSE securities-available-for-trading list is the source universe.
Only `EQ`-series securities are eligible.

For every scan:

1. Load the current NSE EQ-series list, including symbol, company name, ISIN, and
   listing date.
2. Download sufficient daily OHLCV history for feature calculation.
3. Rank stocks by 60-session median traded value (`Close * Volume`).
4. Retain the top 1,000 stocks that have valid traded-value observations on at
   least 40 of the latest 60 completed sessions.
5. Add every EQ-series security listed within the preceding two years, even when
   it is outside the liquidity-ranked top 1,000.
6. Deduplicate by NSE symbol and retain flags for `top_1000_liquid` and
   `recent_ipo_overlay`.

The app will show the source count, usable-history count, final selected count,
recent-IPO additions, and exclusions. A provider failure or insufficient history
is not a negative result.

Recent IPOs may have as few as 15 completed sessions for IPO-specific patterns.
Long-history indicators will report `NOT ELIGIBLE` when the required history is
unavailable. They will not exclude the IPO from screeners that can be computed.

## Architecture

Use a hybrid batch feature engine:

- Universe, OHLCV, benchmark, and corporate-event data are collected once per
  scan through isolated provider adapters.
- A reusable feature matrix calculates price, return, relative-strength, ATR,
  volume, gap, listing-age, and pattern fields.
- Named screeners are pure functions over the feature matrix and, where required,
  compact rolling-window evidence.
- Results, thresholds, match reasons, eligibility, and provenance are persisted
  in the timestamped output bundle.
- The Streamlit tab reads stored artifacts and applies adjustable thresholds
  locally without issuing an untracked network request.

The existing live-breakout workflow remains intact. Technical screeners use the
latest completed daily bar unless a result explicitly says `LIVE`.

## Data Sources

- NSE securities available for trading: official EQ-series universe and listing
  dates.
- Yahoo Finance: adjusted daily OHLCV and existing bounded one-minute quotes.
- Nifty 50 (`^NSEI` through the price adapter): benchmark for the RS-line screen.
- NSE corporate filings: board-meeting financial-result dates and filed-result
  broadcast dates.

Every artifact records source URLs and timestamps. If NSE event data is
unavailable, price-only screeners remain usable while earnings screeners show
`SCAN INCOMPLETE`.

## Screener Catalogue

All numerical defaults below are shown in the UI and can be adjusted before the
stored feature matrix is filtered.

### Create/Load Screener

Provide a local custom-rule builder over exposed feature fields. A rule contains
a field, comparison operator, and numeric or categorical value. Rules use AND
semantics in the first version. Users can save, load, rename, and delete named
screeners in a versioned local JSON file. Invalid or outdated fields are reported
without discarding the saved definition.

### Multiple Scans

Return stocks matching at least two selected named screeners. The user can select
the included screeners and adjust the minimum match count. Results list each
matched screen and the total count.

### Horizontal Resistance

Find at least three swing-high touches during the latest 60 sessions. A swing high
must exceed the highs of the two sessions on either side. Touch prices must fall
within a 2% band, and the latest close must be no more than 5% below the median
touch price. Results show the resistance price, touch count, dispersion, and
distance to resistance.

### Tight Setup

- **NR7:** the latest daily high-low range is the narrowest of seven sessions.
- **Three Tight Closes:** the latest three closes fit within a 1.5% band.
- **ATR Contraction:** latest ATR% is below its 50-session average ATR%.

### IPO Scanner

- **IPO Base:** 15 to 60 completed sessions form a consolidation no deeper than
  20% from high to low.
- **IPO Momentum:** at least 20 sessions, close above SMA20, and a default minimum
  20-session return of 10%.
- **IPO Breakout:** latest close is above the prior 20-session high on at least
  1.5 times 20-session average volume.

IPO screens apply only to securities listed within the preceding two years.

### RS High Before Price High

Calculate the stock/Nifty 50 relative-strength line on aligned completed sessions.
Match when the RS line reaches a 252-session high while the stock remains below
its own 252-session price high. Show both distances from their prior highs.

### Momentum Scanner

Retain the existing weighted momentum score: 40% of 63-session return and 20%
each of 126-, 189-, and 252-session returns, percentile-ranked from 1 to 99.
Default to RS 80+, close above SMA50/SMA150/SMA200, and SMA50 above SMA150 above
SMA200. Each gate and the minimum RS rating are adjustable.

### Volume Screeners

- **Relative-Volume Surge:** latest volume is at least 2.0 times its 20-session
  average.
- **Accumulation Day:** the stock closes higher on at least 1.5 times average
  volume and finishes in the upper half of its daily range.
- **Volume Dry-Up:** latest volume is no more than 0.5 times its 20-session
  average, the close is within 5% of the 20-session high, and the daily range is
  no greater than the median daily range over those 20 sessions.

### VCP

Reuse the existing transparent five-star, Minervini-inspired approximation.
Default to at least four stars and expose the minimum from zero to five. Continue
to show every component's pass/fail evidence and the non-proprietary disclaimer.

### Flags & Pennants

Require a price pole of at least 15% over 10 to 30 sessions followed by a 5 to
20-session consolidation no deeper than 12%. Consolidation volume must contract
relative to pole volume. Results show pole gain, consolidation length and depth,
and volume contraction.

### Earnings Screeners

- **Results Due:** an NSE board-meeting filing identifies financial results due
  within the next 14 calendar days.
- **Fresh Results:** NSE records a financial-result filing within the latest five
  trading sessions.
- **Post-Results Gap-Up:** the first eligible session after a result broadcast
  gaps up at least 4% and trades at least 1.5 times average volume.

An apparent price gap without a matching NSE event does not qualify as an
earnings result.

### Gap Screeners

- **Gap Up:** latest open is at least 3% above the prior close.
- **Gap Down:** latest open is at least 3% below the prior close.
- **Gap-and-Hold:** gap-up criteria pass, the close remains above the prior close,
  and the close finishes in the upper half of the current range.

### Inside Bar

- **Daily Inside Bar:** latest high is below or equal to the previous high and
  latest low is above or equal to the previous low.
- **Double Inside Bar:** the latest two sessions are sequential inside bars.
- **Weekly Inside Bar:** the latest completed week's range is inside the preceding
  completed week's range.

## Streamlit Experience

Add **Screeners** as a sixth top-level tab without changing the current tabs'
meaning. Inside it:

- A left category panel follows the reference image's order.
- Categories with sub-screeners expand in place.
- The right panel shows the selected screener's description, adjustable controls,
  eligibility count, match count, timestamp, and data-status badge.
- Results use a searchable, sortable table with symbol, company, liquidity rank,
  listing date, match reason, and relevant evidence fields.
- Selecting a result opens the existing price-chart and evidence treatment.
- Multiple Scans displays match chips and total match count.
- Create/Load Screener provides local save/load management with clear overwrite
  confirmation.

The tab will follow the existing liquid-glass theme and responsive layout. On
small screens, the category panel stacks above controls and results.

## Artifacts and Contracts

Extend each atomic timestamped bundle with:

- `selected_universe.csv`
- `screener_features.csv`
- `screener_matches.csv`
- `earnings_events.csv`
- expanded `chart_history.csv.gz` for the selected universe

The manifest schema version will increase and include:

- source and selected universe counts
- liquidity and IPO-overlay definitions
- benchmark coverage
- per-feature eligibility counts
- per-screener match counts
- earnings-source status
- thresholds used during the batch calculation
- exclusions grouped by provider and reason

Older output bundles remain readable. The Screeners tab will explain that no
screener artifacts exist and prompt for a new scan.

Saved custom screeners use a separate versioned local JSON file and are not part
of immutable run artifacts.

## Failure Semantics

- `MATCH`: all required data exists and the rule passes.
- `NO MATCH`: all required data exists and the rule fails.
- `NOT ELIGIBLE`: the stock lacks the minimum required history or does not belong
  to the relevant cohort, such as the recent-IPO overlay.
- `SCAN INCOMPLETE`: a required provider or run-level dataset failed or coverage
  fell below its gate.

No missing value is coerced into zero or a failed rule. Custom-rule validation
errors remain local to that definition and do not break preset screeners.

## Testing and Verification

1. Unit-test every rule at its pass/fail boundary, including flat ranges, zero
   volume, split-adjusted prices, short IPO histories, and incomplete weeks.
2. Test NSE universe parsing, EQ filtering, listing-date parsing, deduplication,
   liquidity ranking, and recent-IPO overlay inclusion.
3. Test Nifty 50 alignment and missing-benchmark behavior.
4. Test NSE board-meeting/result parsing and earnings-gap session alignment.
5. Test custom-rule schema validation, save/load/rename/delete behavior, and safe
   migration of unknown fields.
6. Test pipeline artifacts, manifest migration, and incomplete-data semantics.
7. Use Streamlit AppTest for tab presence, category selection, adjustable filters,
   result rendering, and old-bundle messaging.
8. Run a bounded live smoke scan before a full live scan.
9. Run the complete pytest suite and Ruff.
10. Launch Streamlit headlessly, check its health endpoint, and inspect the
    rendered desktop and narrow-screen tab locally.

No deployment is part of this scope.

## Acceptance Criteria

- All reference-image screener categories perform real calculations.
- The selected universe is the top 1,000 by 60-session median traded value plus
  all NSE EQ-series IPOs from the preceding two years.
- Recent IPOs are not rejected solely for lacking 273 sessions.
- Every match exposes its rule evidence and data timestamp.
- Missing or stale data produces an explicit incomplete or ineligible state.
- Existing scanner tabs, live breakout rules, and five-star VCP explanations
  continue to work.
- Tests, lint, Streamlit health, and rendered UI checks pass before completion.
