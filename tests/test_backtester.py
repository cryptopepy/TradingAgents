"""Backtester unit tests — synthetic data, no LLM or network."""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from tradingagents.backtest.engine import (
    LookbackWindow,
    _compute_drawdown,
    _compute_sharpe,
    optimize_strategies,
    run_strategy_on_frame,
)
from tradingagents.backtest.strategies import (
    BollingerMeanReversionStrategy,
    EmaCrossoverStrategy,
    MacdCrossoverStrategy,
    RsiMeanReversionStrategy,
)
from tradingagents.dataflows.dummy_feed import DummyPriceFeed


def _synthetic_ohlcv(rows: int = 120, start: float = 100.0, drift: float = 0.2) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=rows, freq="5min")
    close = start + np.cumsum(np.random.default_rng(42).normal(drift, 1.0, rows))
    close = pd.Series(close, dtype=float)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close * 1.001,
            "Low": close * 0.999,
            "Close": close,
            "Volume": 1_000,
        }
    )


@pytest.mark.unit
class TestTechnicalMetrics:
    def test_sharpe_positive_for_upward_drift(self):
        returns = pd.Series([0.01, 0.02, 0.01, 0.015, 0.005])
        assert _compute_sharpe(returns, periods_per_year=252) > 0

    def test_drawdown_detects_peak_to_trough(self):
        equity = pd.Series([1.0, 1.1, 1.05, 0.9, 0.95])
        assert _compute_drawdown(equity) == pytest.approx(0.1 / 1.1, rel=1e-3)


@pytest.mark.unit
class TestStrategies:
    def test_ema_crossover_produces_signals(self):
        df = _synthetic_ohlcv()
        signals = EmaCrossoverStrategy().generate_signals(df)
        assert set(signals.unique()).issubset({-1, 0, 1})
        assert len(signals) == len(df)

    def test_rsi_mean_reversion_signals(self):
        df = _synthetic_ohlcv()
        signals = RsiMeanReversionStrategy().generate_signals(df)
        assert len(signals) == len(df)

    def test_macd_crossover_signals(self):
        df = _synthetic_ohlcv()
        signals = MacdCrossoverStrategy().generate_signals(df)
        assert set(signals.unique()).issubset({-1, 0, 1})

    def test_bollinger_mean_reversion_signals(self):
        df = _synthetic_ohlcv()
        signals = BollingerMeanReversionStrategy().generate_signals(df)
        assert len(signals) == len(df)


@pytest.mark.unit
class TestStrategyScoring:
    def test_run_strategy_on_frame_metrics(self):
        df = _synthetic_ohlcv(150)
        result = run_strategy_on_frame(df, EmaCrossoverStrategy())
        assert result.num_trades >= 0
        assert isinstance(result.net_profit_ratio, float)
        assert result.max_drawdown >= 0

    def test_optimize_selects_highest_net_profit(self):
        df = _synthetic_ohlcv(150)

        def fake_fetch(symbol, end_date, lookback, **kwargs):
            return df

        with patch("tradingagents.backtest.engine.fetch_historical_crypto", side_effect=fake_fetch):
            opt = optimize_strategies("BTC/USDT", "2025-06-01")

        assert len(opt.results) == 12  # 4 strategies × 3 horizons
        assert opt.winner is not None
        best = max(opt.results, key=lambda r: r.net_profit_ratio)
        assert opt.winner.strategy_name == best.strategy_name
        assert opt.winner.lookback == best.lookback
        assert opt.winner.historical_profit_ratio == best.net_profit_ratio


@pytest.mark.unit
class TestDummyFeed:
    def test_dummy_feed_mutates_price(self):
        feed = DummyPriceFeed(anchor_price=50_000.0, symbol="BTC/USDT", seed=1)
        p1 = feed.fetch_ticker()["last"]
        p2 = feed.fetch_ticker()["last"]
        assert p1 != p2
