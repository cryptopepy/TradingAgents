"""Tests for SQLite OHLCV store."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from tradingagents.backtest.ohlcv_store import OhlcvStore


def _sample_df() -> pd.DataFrame:
    dates = pd.date_range("2024-06-01", periods=40, freq="h")
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.5,
            "Volume": 1000.0,
        }
    )


def test_ohlcv_store_round_trip(tmp_path: Path):
    db = tmp_path / "ohlcv.db"
    store = OhlcvStore(db)
    start = datetime(2024, 6, 1)
    end = datetime(2024, 6, 2, 15, 0)
    df = _sample_df()
    store.put("BTC/USDT", start, end, 3600, df, "test")
    cached = store.get_cached("BTC/USDT", start, end, 3600)
    assert cached is not None
    assert len(cached) == len(df)
    assert float(cached["Close"].iloc[0]) == pytest.approx(100.5)


def test_get_or_fetch_calls_fetch_once(tmp_path: Path):
    db = tmp_path / "ohlcv.db"
    store = OhlcvStore(db)
    start = datetime(2024, 6, 1)
    end = datetime(2024, 6, 2, 15, 0)
    calls = {"n": 0}

    def fetch_fn():
        calls["n"] += 1
        return _sample_df(), "mock"

    df1, src1 = store.get_or_fetch("ETH/USDT", start, end, 3600, fetch_fn)
    df2, src2 = store.get_or_fetch("ETH/USDT", start, end, 3600, fetch_fn)
    assert calls["n"] == 1
    assert len(df1) == len(df2)
    assert src2 == "sqlite cache"
