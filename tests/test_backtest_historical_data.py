"""Regression tests for backtest OHLCV fetch and silent-exit prevention."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cli.post_analysis import run_backtest_with_progress
from tradingagents.backtest import (
    BacktestDataError,
    BacktestValidationError,
    LookbackWindow,
    optimize_strategies,
    require_optimization_results,
)
from tradingagents.backtest.engine import fetch_historical_crypto
from tradingagents.backtest.historical_data import fetch_intraday_ohlcv
from tradingagents.backtest.schemas import OptimizationResult


def _sample_ohlcv(rows: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2026-06-01", periods=rows, freq="5min")
    close = pd.Series(range(100, 100 + rows), dtype=float)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": 1_000,
        }
    )


@pytest.mark.unit
class TestBacktestHistoricalData:
    def test_fetch_intraday_ohlcv_raises_backtest_data_error(self):
        with patch(
            "tradingagents.backtest.historical_data._fetch_cryptocompare_ohlcv",
            side_effect=Exception("HTTP 429"),
        ), patch(
            "tradingagents.backtest.historical_data._fetch_binance_ohlcv",
            side_effect=Exception("451 blocked"),
        ):
            with pytest.raises(BacktestDataError, match="Could not load intraday OHLCV"):
                fetch_intraday_ohlcv(
                    "BTC/USDT",
                    pd.Timestamp("2026-06-01 00:00").to_pydatetime(),
                    pd.Timestamp("2026-06-01 08:00").to_pydatetime(),
                    300,
                )

    def test_optimize_with_mocked_ohlcv_produces_thirty_results(self):
        df = _sample_ohlcv(120)

        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ):
            result = optimize_strategies("BTC/USDT", "2026-06-01")

        assert len(result.results) == 30
        assert result.winner is not None
        require_optimization_results(result)

    def test_run_backtest_with_progress_returns_results(self):
        df = _sample_ohlcv(120)

        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ):
            result = run_backtest_with_progress("BTC/USDT", "2026-06-01")

        assert len(result.results) == 30

    def test_fetch_historical_crypto_caps_end_dt_to_now_for_today(self):
        df = _sample_ohlcv(80)
        noon = datetime(2026, 6, 12, 12, 0, 0)

        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ) as mock_fetch:
            fetch_historical_crypto(
                "BTC/USDT", "2026-06-12", LookbackWindow.H8, now=noon
            )

        start_dt, end_dt = mock_fetch.call_args[0][1], mock_fetch.call_args[0][2]
        assert end_dt == noon
        assert end_dt <= noon
        assert start_dt == end_dt - LookbackWindow.H8.to_timedelta()

    def test_fetch_historical_crypto_uses_end_of_day_for_past_dates(self):
        df = _sample_ohlcv(80)
        noon = datetime(2026, 6, 12, 12, 0, 0)

        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ) as mock_fetch:
            fetch_historical_crypto(
                "BTC/USDT", "2026-06-06", LookbackWindow.H8, now=noon
            )

        end_dt = mock_fetch.call_args[0][2]
        assert end_dt.hour == 23 and end_dt.minute == 59

    def test_fetch_historical_crypto_raises_when_window_empty_after_cap(self):
        noon = datetime(2026, 6, 12, 12, 0, 0)
        zero_lookback = MagicMock()
        zero_lookback.to_timedelta.return_value = timedelta(0)
        zero_lookback.granularity_seconds.return_value = 300
        zero_lookback.value = "8h"

        with pytest.raises(
            BacktestDataError,
            match="Not enough history yet today for 8h window",
        ):
            fetch_historical_crypto(
                "BTC/USDT", "2026-06-12", zero_lookback, now=noon
            )

    def test_fetch_historical_crypto_does_not_call_historic_crypto(self):
        df = _sample_ohlcv(80)
        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ) as mock_fetch, patch(
            "tradingagents.backtest.engine.HistoricalData",
            create=True,
        ) as mock_historic:
            out = fetch_historical_crypto("BTC/USDT", "2026-06-06", LookbackWindow.H8)
            mock_fetch.assert_called_once()
            mock_historic.assert_not_called()
        assert len(out) == 80

    def test_require_optimization_results_surfaces_fetch_warnings(self):
        empty = OptimizationResult(
            symbol="BTC/USDT",
            end_date="2026-06-01",
            results=[],
            warnings=["8h: CryptoCompare timeout", "24h: empty dataframe"],
        )
        with pytest.raises(BacktestValidationError, match="no strategy metrics"):
            require_optimization_results(empty)
