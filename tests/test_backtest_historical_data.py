"""Regression tests for backtest OHLCV fetch and silent-exit prevention."""

import os
import time
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
from tradingagents.backtest.engine import (
    _cache_is_fresh,
    _cache_path,
    _cache_ttl_seconds,
    _last_closed_bar_dt,
    fetch_historical_crypto,
)
from tradingagents.dataflows.config import set_config
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
    def test_cryptocompare_api_error_surfaces_message(self):
        error_payload = {"Response": "Error", "Message": "You are over your rate limit"}

        with patch(
            "tradingagents.dataflows.crypto_common.http_get_json",
            return_value=error_payload,
        ), patch(
            "tradingagents.backtest.historical_data._fetch_binance_ohlcv",
            side_effect=Exception("451 blocked"),
        ):
            with pytest.raises(BacktestDataError, match="rate limit"):
                fetch_intraday_ohlcv(
                    "BTC/USDT",
                    pd.Timestamp("2026-06-01 00:00").to_pydatetime(),
                    pd.Timestamp("2026-06-01 08:00").to_pydatetime(),
                    300,
                )

    def test_fetch_intraday_ohlcv_raises_backtest_data_error(self):
        with patch(
            "tradingagents.backtest.historical_data._fetch_cryptocompare_ohlcv",
            side_effect=Exception("HTTP 429"),
        ), patch(
            "tradingagents.backtest.historical_data._fetch_binance_ohlcv",
            side_effect=Exception("451 blocked"),
        ), patch(
            "tradingagents.backtest.historical_data._fetch_ccxt_ohlcv",
            side_effect=Exception("ccxt unavailable"),
        ):
            with pytest.raises(BacktestDataError, match="Could not load intraday OHLCV"):
                fetch_intraday_ohlcv(
                    "BTC/USDT",
                    pd.Timestamp("2026-06-01 00:00").to_pydatetime(),
                    pd.Timestamp("2026-06-01 08:00").to_pydatetime(),
                    300,
                )

    def test_fetch_intraday_ohlcv_falls_back_to_ccxt(self):
        df = _sample_ohlcv(96)
        with patch(
            "tradingagents.backtest.historical_data._fetch_cryptocompare_ohlcv",
            side_effect=Exception("HTTP 429"),
        ), patch(
            "tradingagents.backtest.historical_data._fetch_binance_ohlcv",
            side_effect=Exception("451 blocked"),
        ), patch(
            "tradingagents.backtest.historical_data._fetch_ccxt_ohlcv",
            return_value=df,
        ) as mock_ccxt:
            out = fetch_intraday_ohlcv(
                "BTC/USDT",
                pd.Timestamp("2026-06-01 00:00").to_pydatetime(),
                pd.Timestamp("2026-06-01 08:00").to_pydatetime(),
                300,
            )
        mock_ccxt.assert_called_once()
        assert len(out) == 96

    def test_optimize_with_mocked_ohlcv_produces_thirty_results(self):
        df = _sample_ohlcv(120)

        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ):
            result = optimize_strategies(
                "BTC/USDT",
                "2026-06-01",
                config={"winner_gate_enabled": False},
            )

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
        expected_end = _last_closed_bar_dt(noon, LookbackWindow.H8.granularity_seconds())

        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ) as mock_fetch:
            fetch_historical_crypto(
                "BTC/USDT", "2026-06-12", LookbackWindow.H8, now=noon
            )

        start_dt, end_dt = mock_fetch.call_args[0][1], mock_fetch.call_args[0][2]
        assert end_dt == expected_end
        assert end_dt < noon
        assert start_dt == end_dt - LookbackWindow.H8.to_timedelta()

    def test_fetch_historical_crypto_floors_end_to_last_closed_bar_for_today(self):
        """Today's intraday window must not request the in-progress candle."""
        df = _sample_ohlcv(80)
        now = datetime(2026, 6, 12, 17, 56, 30)
        granularity = LookbackWindow.H8.granularity_seconds()
        expected_end = _last_closed_bar_dt(now, granularity)

        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ) as mock_fetch:
            fetch_historical_crypto(
                "BTC/USDT", "2026-06-12", LookbackWindow.H8, now=now
            )

        end_dt = mock_fetch.call_args[0][2]
        assert end_dt == expected_end
        assert end_dt.minute % (granularity // 60) == (expected_end.minute % (granularity // 60))
        assert end_dt.second == 0
        assert end_dt < now

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

    def test_last_closed_bar_dt_aligns_to_granularity(self):
        now = datetime(2026, 6, 12, 17, 56, 30)
        for lookback in LookbackWindow:
            g = lookback.granularity_seconds()
            closed = _last_closed_bar_dt(now, g)
            assert closed < now
            assert int(pd.Timestamp(closed).tz_localize("UTC").timestamp()) % g == 0

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


@pytest.mark.unit
class TestBacktestOhlcvCache:
    def _window_df(self, end_date: str, lookback: LookbackWindow, now: datetime) -> pd.DataFrame:
        end_dt, capped = __import__(
            "tradingagents.backtest.engine", fromlist=["_resolve_backtest_end_dt"]
        )._resolve_backtest_end_dt(end_date, now=now)
        if capped:
            end_dt = _last_closed_bar_dt(end_dt, lookback.granularity_seconds())
        start_dt = end_dt - lookback.to_timedelta()
        rows = max(30, int((end_dt - start_dt).total_seconds() / lookback.granularity_seconds()) + 2)
        dates = pd.date_range(start_dt, periods=rows, freq=f"{lookback.granularity_seconds()}s")
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

    def test_cache_hit_skips_vendor_fetch(self, tmp_path):
        noon = datetime(2026, 6, 12, 12, 0, 0)
        df = self._window_df("2026-06-05", LookbackWindow.H8, noon)
        set_config({"data_cache_dir": str(tmp_path)})

        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ) as mock_fetch:
            first = fetch_historical_crypto(
                "BTC/USDT", "2026-06-05", LookbackWindow.H8, now=noon
            )
            second = fetch_historical_crypto(
                "BTC/USDT", "2026-06-05", LookbackWindow.H8, now=noon
            )

        assert len(first) > 0
        assert len(second) > 0
        mock_fetch.assert_called_once()

    def test_cache_miss_after_ttl_expires(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BACKTEST_CACHE_TTL_SECONDS", raising=False)
        noon = datetime(2026, 6, 12, 12, 0, 0)
        df = self._window_df("2026-06-12", LookbackWindow.H8, noon)
        set_config({"data_cache_dir": str(tmp_path), "backtest_cache_ttl_seconds": 60})

        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ) as mock_fetch:
            fetch_historical_crypto("BTC/USDT", "2026-06-12", LookbackWindow.H8, now=noon)
            ticker = "BTC-USD"
            end_dt = _last_closed_bar_dt(noon, LookbackWindow.H8.granularity_seconds())
            start_dt = end_dt - LookbackWindow.H8.to_timedelta()
            cache_file = _cache_path(
                ticker,
                LookbackWindow.H8.granularity_seconds(),
                start_dt.strftime("%Y-%m-%d-%H-%M"),
                end_dt.strftime("%Y-%m-%d-%H-%M"),
            )
            stale_mtime = time.time() - 120
            os.utime(cache_file, (stale_mtime, stale_mtime))
            fetch_historical_crypto("BTC/USDT", "2026-06-12", LookbackWindow.H8, now=noon)

        assert mock_fetch.call_count == 2

    def test_cache_miss_across_day_boundary_for_today(self, tmp_path):
        yesterday = datetime(2026, 6, 11, 23, 30, 0)
        today = datetime(2026, 6, 12, 12, 0, 0)
        df = self._window_df("2026-06-12", LookbackWindow.H8, today)
        set_config({"data_cache_dir": str(tmp_path)})

        with patch(
            "tradingagents.backtest.engine.fetch_intraday_ohlcv",
            return_value=df,
        ) as mock_fetch:
            fetch_historical_crypto("BTC/USDT", "2026-06-12", LookbackWindow.H8, now=yesterday)
            fetch_historical_crypto("BTC/USDT", "2026-06-12", LookbackWindow.H8, now=today)

        assert mock_fetch.call_count == 2

    def test_cache_ttl_defaults_by_granularity(self, monkeypatch):
        monkeypatch.delenv("BACKTEST_CACHE_TTL_SECONDS", raising=False)
        set_config({"backtest_cache_ttl_seconds": 0})
        assert _cache_ttl_seconds(300, capped=True) == 600
        assert _cache_ttl_seconds(900, capped=True) == 900
        assert _cache_ttl_seconds(3600, capped=True) == 3600
        assert _cache_ttl_seconds(300, capped=False) == 86400

    def test_cache_is_fresh_respects_ttl(self, tmp_path):
        cache_file = tmp_path / "sample.csv"
        cache_file.write_text("Date,Close\n", encoding="utf-8")
        end_dt = datetime(2026, 6, 12, 12, 0, 0)
        now = datetime(2026, 6, 12, 12, 1, 0)
        assert _cache_is_fresh(cache_file, 600, capped=True, end_dt=end_dt, now=now) is True
        stale_mtime = time.time() - 700
        os.utime(cache_file, (stale_mtime, stale_mtime))
        assert _cache_is_fresh(cache_file, 600, capped=True, end_dt=end_dt, now=now) is False
