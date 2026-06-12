"""Publication-lag filtering for financial statements."""

import pandas as pd
import pytest

from tradingagents.dataflows.stockstats_utils import filter_financials_by_date


@pytest.mark.unit
class TestFilterFinancialsLag:
    def test_quarterly_lag_45_days(self):
        cols = pd.to_datetime(["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31"])
        data = pd.DataFrame([[1, 2, 3, 4]], columns=cols)
        # 2024-10-15 - 45d publication lag => cutoff 2024-08-31; Q2 and earlier only
        filtered = filter_financials_by_date(data, "2024-10-15", statement_type="quarterly")
        kept = pd.to_datetime(filtered.columns, errors="coerce").dropna()
        assert kept.max() <= pd.Timestamp("2024-06-30")

    def test_annual_lag_90_days(self):
        cols = pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31"])
        data = pd.DataFrame([[1, 2, 3]], columns=cols)
        filtered = filter_financials_by_date(data, "2024-06-01", statement_type="annual")
        kept = pd.to_datetime(filtered.columns, errors="coerce").dropna()
        assert kept.max() <= pd.Timestamp("2023-12-31")
