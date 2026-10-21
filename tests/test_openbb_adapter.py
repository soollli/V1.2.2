from pathlib import Path
import pandas as pd

from src.adapters.data.openbb import OpenBBDataFabricAdapter


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def to_dataframe(self, index=None):
        return pd.DataFrame(self.rows)


class FakeCboeEquity:
    def historical(self, **kwargs):
        return FakeResult([
            {"date": "2026-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            {"date": "2026-01-03", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1100},
        ])

    def quote(self, **kwargs):
        return FakeResult([{"symbol": kwargs["symbol"], "last_price": 102.0}])


class FakeCboe:
    equity = FakeCboeEquity()


class FakeFredEconomy:
    def fred_series(self, **kwargs):
        return FakeResult([{"date": "2026-01-01", "GDP": 100.0}])


class FakeFred:
    economy = FakeFredEconomy()


class FakeSec:
    def company_filings(self, **kwargs):
        return FakeResult([{"symbol": kwargs["symbol"], "form_type": kwargs.get("form_type", "10-K")}])

    def financial_statements(self, **kwargs):
        return FakeResult([{"label": "Revenue", "value": 123}])


class FakeCoverage:
    providers = {"cboe": ["equity.historical"], "fred": ["economy.fred_series"], "sec": ["company_filings"]}


class FakeObb:
    cboe = FakeCboe()
    fred = FakeFred()
    sec = FakeSec()
    coverage = FakeCoverage()


def test_openbb_equity_normalizes_to_terminal_schema():
    a = OpenBBDataFabricAdapter(obb_client=FakeObb())
    df = a.equity_history("AAPL")
    assert list(df.columns) == ["open_time", "open", "high", "low", "close", "volume", "close_time"]
    assert len(df) == 2
    assert float(df.iloc[-1]["close"]) == 102.0
    assert str(df.iloc[0]["open_time"].tz) == "UTC"


def test_openbb_macro_filings_and_health():
    a = OpenBBDataFabricAdapter(obb_client=FakeObb())
    assert not a.fred_series("GDP").empty
    assert a.company_filings("AAPL", "10-K").iloc[0]["form_type"] == "10-K"
    assert a.financial_statements("AAPL").iloc[0]["label"] == "Revenue"
    assert a.health(network=True)["ok"] is True
    assert "cboe" in a.coverage()["providers"]
