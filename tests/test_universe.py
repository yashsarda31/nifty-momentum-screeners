import pandas as pd
import pytest

from nifty_vcp.universe import fetch_universe, parse_universe_csv


def universe_csv(count=650):
    rows = [f"Company {i},Industry {i % 4},SYM{i},EQ" for i in range(count)]
    return (
        "Company Name,Industry,Symbol,Series\n" + "\n".join(rows)
    ).encode()


def test_parse_universe_normalizes_symbols_and_columns():
    frame = parse_universe_csv(universe_csv())
    assert list(frame.columns) == [
        "symbol",
        "company_name",
        "industry",
        "yahoo_symbol",
    ]
    assert frame.loc[0, "symbol"] == "SYM0"
    assert frame.loc[0, "yahoo_symbol"] == "SYM0.NS"
    assert len(frame) == 650


def test_parse_universe_rejects_duplicates_and_bad_count():
    duplicate = universe_csv() + b"\nDuplicate,IT,SYM0,EQ"
    with pytest.raises(ValueError, match="duplicate symbols"):
        parse_universe_csv(duplicate)
    with pytest.raises(ValueError, match="between 650 and 850"):
        parse_universe_csv(universe_csv(10))


def test_parse_universe_filters_non_equity_series():
    content = universe_csv() + b"\nDebt security,Debt,DEBT,N1"
    result = parse_universe_csv(content)
    assert "DEBT" not in set(result["symbol"])


def test_fetch_universe_sets_headers_timeout_and_checks_status():
    class Response:
        content = universe_csv()

        def __init__(self):
            self.checked = False

        def raise_for_status(self):
            self.checked = True

    class Session:
        def __init__(self):
            self.response = Response()
            self.kwargs = None

        def get(self, _url, **kwargs):
            self.kwargs = kwargs
            return self.response

    session = Session()
    result = fetch_universe(session=session, timeout=12.5)
    assert isinstance(result, pd.DataFrame)
    assert session.response.checked
    assert session.kwargs["timeout"] == 12.5
    assert "Mozilla" in session.kwargs["headers"]["User-Agent"]

