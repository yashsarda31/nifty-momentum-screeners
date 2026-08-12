# Nifty Total Market Momentum + VCP Scanner

A local research scanner for the official Nifty Total Market universe. It ranks stocks by weighted price momentum, inspects RS 80+ stocks for a strict live 55-session breakout, and explains a transparent five-star, Minervini-inspired VCP score in a liquid-glass Streamlit dashboard.

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

Full official universe:

```powershell
.\.venv\Scripts\python.exe scan.py --output-dir outputs
```

An incomplete scan exits with code 2 while preserving diagnostics. This is deliberate: missing coverage must not be mistaken for no signal.

## Dashboard

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL printed by Streamlit. The dashboard reads the latest completed artifact bundle from `outputs/latest.json`. Its **Run Live Scan** button executes the same pipeline in-process.

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
- `UNAVAILABLE`, `DELAYED`, and `LAST AVAILABLE` quote labels remain distinct from a valid live non-breakout.

Each timestamped output directory contains:

- `all_rankings.csv`
- `high_rs_setups.csv`
- `live_breakouts.csv`
- `exclusions.csv`
- `chart_history.csv.gz`
- `run_manifest.json`

`latest.json` is atomically replaced only after every artifact has been written.

## Sources and limitations

- Universe: official [Nifty Total Market constituent file](https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv).
- Prices: Yahoo Finance through `yfinance`; unofficial, potentially delayed, and not suitable as an exchange-grade execution feed.
- NSE holidays are inferred from the modal latest completed daily bar across the universe. A symbol behind that cross-sectional reference date is explicitly marked stale.
- Constituents are current, so historical ranks are not point-in-time universe backtests.
