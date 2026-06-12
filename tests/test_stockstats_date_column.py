"""Tests for tolerating a non-`Date` index column in crypto_candles."""

from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows import crypto_candles as cc


def _ohlcv(date_col: str) -> pd.DataFrame:
    dates = pd.date_range("2026-04-01", periods=10, freq="D")
    return pd.DataFrame({
        date_col: dates,
        "Open": [100.0 + i for i in range(10)],
        "High": [101.0 + i for i in range(10)],
        "Low": [99.0 + i for i in range(10)],
        "Close": [100.5 + i for i in range(10)],
        "Volume": [1_000_000 + i for i in range(10)],
    })


@pytest.mark.unit
class TestEnsureDateColumn:
    def test_renames_index_column(self):
        out = cc._ensure_date_column(_ohlcv("index"))
        assert "Date" in out.columns and "index" not in out.columns

    def test_leaves_existing_date_untouched(self):
        df = _ohlcv("Date")
        assert cc._ensure_date_column(df) is df


@pytest.mark.unit
class TestCleanDataframe:
    def test_clean_handles_index_column(self):
        cleaned = cc._clean_dataframe(_ohlcv("index"))
        assert "Date" in cleaned.columns
        assert len(cleaned) == 10
