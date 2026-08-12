# Nifty Total Market Momentum, Breakout, and VCP Scanner

## Objective

Build a standalone Python scanner and local Streamlit dashboard for the official Nifty Total Market universe. The scanner ranks stocks by relative strength, checks high-relative-strength stocks for a live 55-session breakout, and assigns each qualifying setup a transparent five-star, Minervini-inspired VCP rating.

This is a research and screening tool, not an order-entry system or investment recommendation.

## Scope

The project will:

- Fetch the current official Nifty Total Market constituent list from NSE Indices.
- Fetch enough adjusted daily OHLCV history to calculate 12-month momentum, moving averages, ATR, price ranges, and volume conditions.
- Calculate a cross-sectional relative-strength rating for every stock with valid data.
- Restrict live quote fetching and VCP scoring to stocks with an RS rating of at least 80.
- Detect a live breakout above the highest completed-session high from the previous 55 sessions.
- Provide a local Streamlit dashboard and timestamped CSV outputs.
- Make stale, missing, and incomplete data visible.

The first release will not place trades, send alerts, use fundamental data, detect chart patterns with machine learning, or deploy to a hosted service.

## Data Sources and Universe

The universe source is the official Nifty Total Market constituent CSV:

`https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv`

NSE Indices describes Nifty Total Market as the combination of Nifty 500 and Nifty Microcap 250. Its actual constituent count can temporarily differ from 750 because of index events. The scanner will therefore validate uniqueness and a reasonable count range rather than require exactly 750 rows.

Yahoo Finance data, accessed with `yfinance`, will provide:

- Adjusted daily OHLCV for approximately 15 calendar months.
- One-minute intraday data for high-RS stocks only.

Yahoo data is unofficial, may be delayed, is intended for personal research use, and is not exchange-grade. Every result will display its source and timestamp.

## Processing Flow

1. Download and validate the official constituent CSV.
2. Convert NSE symbols to Yahoo `.NS` tickers while retaining the original NSE symbol and company name.
3. Fetch daily adjusted OHLCV in bounded batches with retries.
4. Remove any unfinished current-session daily bar before calculating historical features.
5. Validate each symbol independently and record exclusions with explicit reasons.
6. Calculate weighted momentum and cross-sectional RS ratings.
7. Select stocks with RS ratings of 80 or higher.
8. Calculate the five VCP components using completed daily bars.
9. Fetch one-minute intraday quotes for the high-RS subset.
10. Compare the latest valid quote with the prior 55 completed-session high.
11. Write atomic, timestamped CSV outputs and update the dashboard's latest-run manifest.

## Relative-Strength Model

For each stock, calculate total adjusted-price returns over approximately 63, 126, 189, and 252 trading sessions. Its weighted momentum is:

`0.40 * return_63d + 0.20 * return_126d + 0.20 * return_189d + 0.20 * return_252d`

The RS rating is the percentile rank of weighted momentum across all stocks with valid history, mapped to integer values from 1 through 99. Higher values indicate stronger price performance relative to the current universe. "High RS" means an RS rating of at least 80.

The output will also retain each component return so the ranking is auditable. This rating is a transparent cross-sectional measure, not the proprietary Investor's Business Daily RS Rating.

## Live Breakout Definition

The pivot is the maximum adjusted daily high over the previous 55 completed trading sessions. The current unfinished daily candle is never part of the pivot.

A stock is breaking out when:

`latest_valid_intraday_price > prior_55_session_high`

The output will include the live price, pivot, breakout percentage, quote timestamp, quote age, and breakout status. Equality with the pivot is not a breakout.

Outside NSE market hours, the dashboard will clearly label the quote as the most recent available intraday observation rather than imply that it is live. If a quote is missing or stale, the stock is marked `QUOTE UNAVAILABLE`; it is not classified as `NO BREAKOUT`.

## Five-Star VCP Rating

Mark Minervini has not published an official mechanical five-star VCP formula. This project implements a documented, Minervini-inspired approximation. Each high-RS stock earns one star for each condition below, calculated from completed daily bars.

### 1. Trend Template

- Close is above SMA50.
- SMA50 is above SMA150.
- SMA150 is above SMA200.
- SMA200 is higher than it was 20 sessions earlier.

All four conditions must pass for the star.

### 2. Position in the 52-Week Range

- Close is at least 85% of the 252-session high.
- Close is at least 30% above the 252-session low.

Both conditions must pass for the star.

### 3. Contracting Price Ranges

For 60-, 30-, and 15-session windows, normalized range is:

`(window_high - window_low) / window_low`

The star passes when the ranges contract strictly from 60 to 30 to 15 sessions and the 15-session range is no more than 60% of the 60-session range.

### 4. Contracting Volatility

Calculate Wilder true range and mean ATR over 50, 20, and 10 sessions, normalized by the latest close. The star passes when:

`ATR_10_pct < ATR_20_pct < ATR_50_pct`

### 5. Pivot Readiness and Volume Dry-Up

- The latest completed close is no more than 5% below the prior 55-session pivot.
- Average volume over 10 sessions is no more than 75% of average volume over 50 sessions.

Both conditions must pass for the star.

The dashboard will show the total from zero to five and the evidence for each star. A high score is a screening aid, not proof that a discretionary VCP exists.

## Dashboard Design

The local Streamlit interface will use an Apple-inspired liquid-glass aesthetic without copying Apple assets:

- Dark aurora gradient background.
- Translucent panels with blur, subtle highlights, spectral borders, and restrained motion.
- High-contrast typography and accessible status colors.
- Responsive layout for desktop and tablet.

The header will show the scan timestamp, NSE market-state label, data-source badge, overall freshness, and a prominent **Run Live Scan** control.

Summary cards will show:

- Valid historical coverage.
- Number of high-RS stocks.
- Number of live breakouts.
- Number of exclusions or failures.

The dashboard will contain these views:

1. **Live Breakouts**: cards and a sortable table with symbol, company, live price, pivot, breakout percentage, RS rating, VCP stars, and quote age.
2. **RS Leaders**: searchable and filterable leaderboard with momentum components and VCP score.
3. **All Stocks**: the complete valid universe ranking.
4. **Scan Health**: coverage, stale data, missing symbols, retry results, and provider errors.
5. **Methodology**: formulas, thresholds, data limitations, and interpretation guidance.

Selecting a stock will show a 12-month candlestick chart with volume, SMA50, SMA150, SMA200, and the 55-session pivot, plus the five VCP pass/fail explanations.

## Outputs

Each run will write a timestamped directory containing:

- `all_rankings.csv`
- `high_rs_setups.csv`
- `live_breakouts.csv`
- `exclusions.csv`
- `run_manifest.json`

The manifest will include start and finish times, data-source URLs, requested and valid counts, quote coverage, market-state label, thresholds, and overall status. A `latest.json` pointer will be replaced atomically only after the run finishes.

## Reliability and Failure Semantics

Network calls will use bounded batches, timeouts, retry limits, and exponential backoff with jitter. A failed batch will be retried in smaller groups so one symbol cannot invalidate the whole batch.

Historical frames must have:

- Required OHLCV columns.
- A unique, increasing datetime index.
- Finite, positive prices and nonnegative volume.
- Enough completed sessions for all required calculations.
- A latest completed bar matching the modal latest completed-session date across the valid universe; older symbols are marked stale. This cross-sectional reference avoids treating an exchange holiday as a missing session.

Run status is:

- `COMPLETE`: at least 90% valid historical coverage and at least 90% live-quote coverage among high-RS stocks.
- `SCAN INCOMPLETE`: either coverage threshold is missed or the official universe cannot be validated.

No-result semantics are explicit:

- `NO BREAKOUTS`: a complete scan found none.
- `SCAN INCOMPLETE`: insufficient trustworthy coverage; never presented as no breakouts.

Partial outputs remain available for diagnosis, but the UI prominently displays the incomplete status.

## Architecture

The code will be divided into focused modules:

- `universe.py`: constituent download and validation.
- `market_data.py`: historical and intraday Yahoo adapters, batching, retries, and session handling.
- `momentum.py`: returns, weighted momentum, and RS percentiles.
- `vcp.py`: five-star criteria and evidence.
- `breakouts.py`: pivot and live-breakout classification.
- `pipeline.py`: orchestration, coverage gates, and output writing.
- `app.py`: Streamlit dashboard only; analytical logic stays outside the UI.
- `models.py`: typed result and status records.

External data access will be dependency-injected so tests use deterministic local frames and do not require the network.

## Testing and Acceptance Criteria

Implementation will follow test-first development. Unit tests will cover:

- Constituent parsing, duplicate rejection, and count validation.
- Trading-session and unfinished-bar handling.
- Return horizons and weighted momentum.
- Cross-sectional RS percentile ranking, including ties and missing histories.
- Every VCP star at its pass/fail boundary.
- The strict live-price-above-pivot breakout rule.
- Quote staleness and outside-market-hours labels.
- Batch failure isolation, retry limits, and coverage status.
- Atomic output creation and manifest contents.

Integration verification will include:

- A small live smoke scan against a bounded symbol subset.
- A full-universe run if Yahoo permits adequate coverage during validation.
- Streamlit startup and HTTP health check.
- Inspection of generated CSV schemas and the dashboard's latest-run loading path.

Acceptance requires all automated tests to pass, the dashboard to launch locally, timestamps and sources to be visible, and incomplete data to remain distinguishable from a valid no-breakout result.

## Dependencies and Operation

The intended runtime is an isolated Python virtual environment. Expected packages are `pandas`, `numpy`, `requests`, `yfinance`, `streamlit`, `plotly`, and `pytest`.

The project will provide concise Windows commands to create the environment, run tests, execute the scanner, and launch the dashboard. No deployment is included in this scope.

## Primary References

- NSE Indices, Nifty Total Market: https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-total-market
- Official constituent CSV: https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv
- yfinance download API: https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
- yfinance usage and legal disclaimer: https://ranaroussi.github.io/yfinance/index.html
