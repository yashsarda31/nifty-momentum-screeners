# Yfinance Startup Price Snapshot Design

**Date:** 2026-08-14  
**Status:** User-approved design  
**Application:** Nifty Total Market Momentum + VCP Scanner

## Goal

Fetch the latest available Yahoo Finance price for the expanded screener universe
when a browser session first loads the Streamlit app. A manual browser refresh
must start a new fetch. The app will not poll continuously or reuse prices across
browser sessions.

## Product Decisions

- Yahoo Finance through `yfinance` remains the price provider.
- Fetch one bulk intraday snapshot for every symbol in the loaded selected
  universe, including the top-liquidity set and recent-IPO overlay.
- Do not use `st.cache_data`, a time-to-live cache, a disk cache, or a shared
  process cache for startup quotes.
- Keep the successfully fetched snapshot only in `st.session_state`. Streamlit
  widget reruns within the same browser session reuse that snapshot and do not
  create additional provider traffic.
- A manual browser refresh creates a new Streamlit session and therefore requests
  a fresh snapshot.
- Completed daily bars remain the source for all technical screener calculations.
  Startup quotes update displayed prices and live breakout classification only.

## Data Flow

1. Load the latest persisted scan bundle as the app does today.
2. Read `symbol` and `yahoo_symbol` from `selected_universe.csv`.
3. On the first render of a browser session, call a dedicated startup-quote
   service using batched `yfinance.download` requests with one-minute data for the
   current trading day.
4. Isolate failed batches and symbols using the existing bounded retry strategy.
5. Reduce each valid symbol response to its latest finite close and timestamp.
6. Classify each result as `LIVE`, `DELAYED`, `LAST AVAILABLE`, or `UNAVAILABLE`
   using the current India-market session rules.
7. Store the resulting quote table and fetch metadata in `st.session_state`.
8. Merge the snapshot into in-memory copies of rankings, high-RS setups, and
   screener features. Do not modify the timestamped scan bundle on disk.

The startup snapshot will have one row per selected symbol so that a provider
failure remains visible rather than silently dropping the stock.

## User Interface

Price-bearing tables will expose these fields where applicable:

- `latest_price`
- `quote_timestamp`
- `quote_status`
- `price_change_pct`, calculated against the latest completed daily close

The app header will show when the startup snapshot finished and how many selected
symbols received usable quotes. The existing scan timestamp remains visible and
distinct from the startup quote timestamp.

If a quote is unavailable, the app will continue showing the completed daily
close in its existing field and mark the live quote as `UNAVAILABLE`. It will not
label the historical close as a current price.

## Breakout Behaviour

After the startup snapshot loads, high-RS setups will be reclassified in memory
against the stored prior 55-completed-session pivot. Only a quote classified as
`LIVE` may confirm a live breakout while the NSE cash market is open. Delayed or
closed-market observations remain visible but cannot be presented as a live
breakout.

No other screener rule will use the startup quote. This avoids mixing incomplete
intraday candles with completed-session indicators.

## Failure Handling

- Individual Yahoo failures produce `UNAVAILABLE` rows with a reason.
- Partial provider coverage does not block the rest of the app.
- A total provider failure leaves the persisted scan fully usable and displays a
  clear startup-quote warning.
- Invalid, non-positive, or non-finite prices are rejected.
- Quote age and market state determine status; the UI will not claim that Yahoo
  data is exchange-grade real time.
- Network calls use bounded batches, timeouts, retries, and failure isolation.

## Testing

Automated tests will verify:

- one latest quote is produced per selected symbol, including unavailable rows;
- timestamps and `LIVE`, `DELAYED`, and `LAST AVAILABLE` classifications;
- invalid prices and partial provider failures;
- startup quotes are fetched once per Streamlit browser session;
- ordinary Streamlit reruns reuse session state without another Yahoo request;
- a new session has no stored snapshot and performs a new request;
- table merges preserve every selected symbol and the completed daily close;
- only live high-RS quotes can confirm breakouts;
- the app remains usable when all startup quote requests fail.

Verification will run targeted tests first, followed by the full pytest suite and
Ruff. A local Streamlit smoke test will confirm the health endpoint and rendered
quote-status fields without deploying.

## Non-Goals

- Continuous polling, background refresh, or one-minute auto-refresh.
- Broker, paid NSE, or WebSocket market-data integration.
- Persisting startup quotes into the atomic scan bundle.
- Recalculating daily technical indicators from an unfinished intraday candle.
- Placing orders or presenting the data as suitable for execution.
