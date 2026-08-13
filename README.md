# NSE Momentum + VCP Scanner

A local research scanner for a broad NSE equity universe. It ranks stocks by weighted price momentum, inspects RS 80+ stocks for a strict live 55-session breakout, and provides 23 auditable preset screeners plus saved custom rules in a liquid-glass Streamlit dashboard.

This project does not place orders or provide investment advice. Yahoo Finance data is unofficial, may be delayed, and is intended for personal research use.

## Windows setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

## Scan

Bounded provider smoke test:

```powershell
.\.venv\Scripts\python.exe scan.py --max-symbols 10 --output-dir outputs-smoke
```

Full official NSE EQ universe:

```powershell
.\.venv\Scripts\python.exe scan.py --output-dir outputs
```

The scanner downloads the official NSE `EQ` list, ranks names by median `Close × Volume` over the latest 60 sessions (minimum 40 observations), selects the top 1,000, and then adds every IPO listed in the preceding two years. IPO-specific rules can start at 15 completed sessions; longer-history rules report `NOT ELIGIBLE`.

A full scan downloads roughly two years of daily data for the exchange list and can take several minutes depending on Yahoo/NSE responsiveness. An incomplete scan exits with code 2 while preserving diagnostics. This is deliberate: missing coverage must not be mistaken for no signal.

## Dashboard

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL printed by Streamlit. The dashboard reads the latest completed artifact bundle from `outputs/latest.json`. Its **Run Live Scan** button executes the same pipeline in-process.

The separate **Screeners** tab includes:

- Horizontal resistance; NR7, three tight closes, and ATR contraction.
- IPO base, IPO momentum, and IPO breakout.
- RS high before price high; momentum; relative-volume, accumulation, and dry-up screens.
- VCP; flags and pennants; results due, fresh results, and post-results gap-up.
- Gap up, gap down, gap and hold; daily, double, and weekly inside bars.
- Multiple-scan intersections and locally saved custom AND rules.

Preset thresholds are editable in the tab and are recalculated from the stored evidence without another network request. Custom rules are stored in the ignored local file `custom_screeners.json`.

## Methodology

### Relative strength

Weighted momentum is:

```text
40% × 63-session return
+ 20% × 126-session return
+ 20% × 189-session return
+ 20% × 252-session return
```

Stocks are cross-sectionally percentile-ranked from 1 through 99. RS 80 or higher is considered high RS. This is not the proprietary IBD RS Rating.

### Live breakout

The scanner obtains one-minute Yahoo observations only for high-RS stocks. A breakout requires a valid `LIVE` observation strictly above the highest daily high from the previous 55 completed sessions. Equality is not a breakout. Delayed, missing, and closed-market observations cannot confirm a live breakout.

### Five VCP stars

One star is awarded for each documented condition:

1. Close > SMA50 > SMA150 > SMA200, with SMA200 rising versus 20 sessions ago.
2. Close is within 15% of the 252-session high and at least 30% above the low.
3. Normalized 60-, 30-, and 15-session ranges contract sequentially, with the final range no more than 60% of the first.
4. ATR% contracts from 50 to 20 to 10 sessions.
5. Close is within 5% below the 55-session pivot and 10-session average volume is no more than 75% of 50-session average volume.

Mark Minervini has not published an official mechanical five-star VCP formula. This score is an auditable approximation and does not establish that a discretionary VCP is present.

## Result semantics

- `COMPLETE` means at least 90% of the requested universe has valid history and at least 90% of high-RS stocks have usable quotes.
- `NO BREAKOUTS` means a complete scan found no confirmed live breakouts.
- `SCAN INCOMPLETE` means provider/universe coverage was insufficient. It never means no breakouts.
- `MATCH` and `NO MATCH` are emitted only when all evidence required by that screener is available.
- `NOT ELIGIBLE` means the stock lacks enough history or another rule-specific input.
- `UNAVAILABLE`, `DELAYED`, and `LAST AVAILABLE` quote labels remain distinct from a valid live non-breakout.

Each timestamped output directory contains:

- `all_rankings.csv`
- `high_rs_setups.csv`
- `live_breakouts.csv`
- `exclusions.csv`
- `chart_history.csv.gz`
- `selected_universe.csv`
- `screener_features.csv`
- `screener_matches.csv`
- `earnings_events.csv`
- `run_manifest.json`

`latest.json` is atomically replaced only after every artifact has been written.

## Sources and limitations

- Universe: official [NSE securities available for trading list](https://archives.nseindia.com/content/equities/EQUITY_L.csv), filtered to the `EQ` series.
- Prices: Yahoo Finance through `yfinance`; unofficial, potentially delayed, and not suitable as an exchange-grade execution feed.
- Earnings events: official NSE board-meeting and integrated-financial-results endpoints. Provider failure marks only dependent screeners `SCAN INCOMPLETE`.
- NSE holidays are inferred from the modal latest completed daily bar across the universe. A symbol behind that cross-sectional reference date is explicitly marked stale.
- The securities list and liquidity selection are current, so historical ranks are not point-in-time universe backtests.
