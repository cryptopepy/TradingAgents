"""Tests for the mathematical backtesting engine."""

from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.backtest.engine import LookbackWindow, fetch_historical_price_slice, run_strategy_backtest


def _sample_ohlcv(rows: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=rows, freq="B")
    close = pd.Series(range(100, 100 + rows), dtype=float)
    return pd.DataFrame({"Date": dates, "Close": close, "Open": close, "High": close, "Low": close, "Volume": 1_000})


@pytest.mark.unit
class TestBacktestEngine:
    def test_fetch_historical_price_slice_placeholder(self):
        df = _sample_ohlcv()
        with patch("tradingagents.backtest.engine.load_ohlcv", return_value=df):
            slice_df = fetch_historical_price_slice("SPY", "2025-03-01", lookback_hours=24 * 7)
        assert not slice_df.empty
        assert slice_df["Date"].max() <= pd.Timestamp("2025-03-01")

    def test_run_strategy_backtest_returns_metrics(self):
        df = _sample_ohlcv(80)
        with patch("tradingagents.backtest.engine.fetch_historical_price_slice", return_value=df):
            result = run_strategy_backtest("SPY", "2025-04-01", lookback=LookbackWindow.D7)
        assert result.symbol == "SPY"
        assert result.lookback == LookbackWindow.D7
        assert isinstance(result.total_return_pct, float)
        assert result.num_trades >= 0

    def test_insufficient_data_note(self):
        df = _sample_ohlcv(5)
        with patch("tradingagents.backtest.engine.fetch_historical_price_slice", return_value=df):
            result = run_strategy_backtest("SPY", "2025-04-01", lookback=LookbackWindow.H8)
        assert result.num_trades == 0
        assert result.notes
