"""Tests for OHLCV vendor fallback when bar counts are insufficient."""

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.backtest.historical_data import fetch_intraday_ohlcv
from tradingagents.dataflows.symbol_utils import NoMarketDataError


def _tiny_df(n: int) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    return pd.DataFrame(
        {
            "Date": pd.date_range(now, periods=n, freq="5min"),
            "Open": [1.0] * n,
            "High": [1.0] * n,
            "Low": [1.0] * n,
            "Close": [1.0] * n,
            "Volume": [0.0] * n,
        }
    )


def _full_df(n: int = 40) -> pd.DataFrame:
    return _tiny_df(n)


@pytest.mark.unit
class TestIntradayOhlcvVendorFallback:
    def test_tries_next_vendor_when_first_returns_insufficient_bars(self):
        attempts: list[tuple[str, int, bool, str]] = []

        def _on_attempt(vendor: str, bars: int, ok: bool, detail: str) -> None:
            attempts.append((vendor, bars, ok, detail))

        start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)

        with patch(
            "tradingagents.backtest.historical_data._fetch_ccxt_ohlcv_from_exchange",
            return_value=_tiny_df(12),
        ), patch(
            "tradingagents.backtest.historical_data._fetch_binance_ohlcv",
            return_value=_full_df(48),
        ), patch(
            "tradingagents.backtest.historical_data.ccxt_exchange_ids",
            return_value=("kraken",),
        ):
            df = fetch_intraday_ohlcv(
                "BTC/USDT",
                start,
                end,
                300,
                on_provider_attempt=_on_attempt,
                min_bars=30,
            )

        assert len(df) == 48
        assert any(v == "kraken" and not ok for v, _, ok, _ in attempts)
        assert any(v == "Binance" and ok for v, _, ok, _ in attempts)

    def test_raises_when_all_vendors_insufficient_or_fail(self):
        start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)

        with patch(
            "tradingagents.backtest.historical_data._fetch_binance_ohlcv",
            side_effect=NoMarketDataError("BTC/USDT", "BTC/USDT", "blocked"),
        ), patch(
            "tradingagents.backtest.historical_data._fetch_cryptocompare_ohlcv",
            side_effect=NoMarketDataError("BTC/USDT", "BTC/USDT", "rate limited"),
        ), patch(
            "tradingagents.backtest.historical_data.ccxt_exchange_ids",
            return_value=("kraken",),
        ), patch(
            "tradingagents.backtest.historical_data._fetch_ccxt_ohlcv_from_exchange",
            return_value=_tiny_df(8),
        ):
            from tradingagents.backtest.validation import BacktestDataError

            with pytest.raises(BacktestDataError):
                fetch_intraday_ohlcv(
                    "BTC/USDT",
                    start,
                    end,
                    300,
                    min_bars=30,
                )


@pytest.mark.unit
class TestCcxtOhlcvPagination:
    def test_naive_utc_ms_treats_wall_clock_as_utc(self):
        from tradingagents.backtest.historical_data import _naive_utc_ms

        dt = datetime(2026, 6, 13, 7, 35)
        assert _naive_utc_ms(dt) == 1781336100000

    def test_pages_until_window_filled(self):
        from tradingagents.backtest.historical_data import (
            _fetch_ccxt_ohlcv_from_exchange,
            _naive_utc_ms,
        )

        start = datetime(2026, 6, 1, 0, 0)
        end = datetime(2026, 6, 1, 8, 0)
        base_ms = _naive_utc_ms(start)
        end_ms = _naive_utc_ms(end)
        step_ms = 5 * 60 * 1000

        call_count = 0

        def _fake_batch(symbol, interval, since=None, limit=1000):
            nonlocal call_count
            call_count += 1
            batch = []
            ts = since or base_ms
            for _ in range(25):
                if ts >= end_ms:
                    break
                batch.append([ts, 1, 1, 1, 1, 0])
                ts += step_ms
            return batch

        mock_exchange = type(
            "Ex",
            (),
            {"load_markets": lambda self: None, "markets": {"BTC/USD": {}}},
        )()
        captured_since: list[int] = []

        def _fake_batch_capture(symbol, interval, since=None, limit=1000):
            captured_since.append(since)
            return _fake_batch(symbol, interval, since, limit)

        mock_exchange.fetch_ohlcv = _fake_batch_capture

        import sys
        from unittest.mock import MagicMock

        mock_ccxt = MagicMock()
        mock_ccxt.kraken = lambda config: mock_exchange

        with patch.dict(sys.modules, {"ccxt": mock_ccxt}), patch(
            "tradingagents.backtest.historical_data._ccxt_market_symbol",
            return_value="BTC/USD",
        ):
            df = _fetch_ccxt_ohlcv_from_exchange("kraken", "BTC/USDT", start, end, "5m")

        assert call_count >= 2
        assert len(df) >= 25
        assert captured_since[0] == base_ms
