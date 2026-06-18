"""Backtester unit tests — synthetic data, no LLM or network."""

from datetime import datetime
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
from tradingagents.backtest.matcher import SimulatedMatcher
from tradingagents.backtest.portfolio import (
    Direction,
    TransactionIntent,
    VirtualPortfolio,
    signals_to_intents,
)
from tradingagents.backtest.strategies import (
    DEFAULT_STRATEGIES,
    STRATEGY_REGISTRY,
    AdxTrendFilterStrategy,
    ApoCrossoverStrategy,
    BollingerMeanReversionStrategy,
    CciBreakoutStrategy,
    CmoMeanReversionStrategy,
    EmaCrossoverStrategy,
    MacdCrossoverStrategy,
    RsiMeanReversionStrategy,
    TrixMomentumStrategy,
    VwapBandMeanReversionStrategy,
    build_default_strategies,
    compute_adx,
    compute_apo,
    compute_cci,
    compute_chande_momentum_oscillator,
    compute_trix,
    compute_vwap_bands,
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


def _trending_ohlcv(rows: int = 80) -> pd.DataFrame:
    """Monotonic uptrend for boundary / crossover tests."""
    dates = pd.date_range("2025-01-01", periods=rows, freq="1h")
    close = pd.Series(np.linspace(100, 200, rows), dtype=float)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 2,
            "Low": close - 2,
            "Close": close,
            "Volume": np.full(rows, 5_000.0),
        }
    )


def _mean_reverting_ohlcv(rows: int = 80) -> pd.DataFrame:
    """Oscillating prices for mean-reversion indicators."""
    dates = pd.date_range("2025-01-01", periods=rows, freq="1h")
    t = np.arange(rows)
    close = pd.Series(100 + 10 * np.sin(t / 3), dtype=float)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 1.5,
            "Low": close - 1.5,
            "Close": close,
            "Volume": np.full(rows, 2_000.0),
        }
    )


@pytest.mark.unit
class TestTechnicalMetrics:
    def test_sharpe_positive_for_upward_drift(self):
        returns = pd.Series([0.01, 0.02, 0.01, 0.015, 0.005])
        assert _compute_sharpe(returns, periods_per_year=252) > 0

    def test_drawdown_detects_peak_to_trough(self):
        equity = pd.Series([1.0, 1.1, 1.05, 0.9, 0.95])
        assert _compute_drawdown(equity) == pytest.approx((1.1 - 0.9) / 1.1, rel=1e-3)


@pytest.mark.unit
class TestIndicators:
    def test_cmo_bounded(self):
        df = _synthetic_ohlcv(60)
        cmo = compute_chande_momentum_oscillator(df, period=14)
        valid = cmo.dropna()
        assert len(valid) > 0
        assert valid.min() >= -100
        assert valid.max() <= 100

    def test_adx_components_positive(self):
        df = _trending_ohlcv(60)
        adx, plus_di, minus_di = compute_adx(df, period=14)
        valid_adx = adx.dropna()
        assert (valid_adx >= 0).all()
        assert len(plus_di.dropna()) > 0
        assert len(minus_di.dropna()) > 0

    def test_vwap_bands_ordering(self):
        df = _synthetic_ohlcv(60)
        vwap, upper, lower = compute_vwap_bands(df, period=20)
        mask = upper.notna() & lower.notna()
        assert (upper[mask] >= lower[mask]).all()
        assert (vwap[mask] >= lower[mask]).all()
        assert (upper[mask] >= vwap[mask]).all()

    def test_cci_finite(self):
        df = _mean_reverting_ohlcv(60)
        cci = compute_cci(df, period=20)
        valid = cci.dropna()
        assert len(valid) > 0
        assert np.isfinite(valid).all()

    def test_trix_and_signal_same_length(self):
        df = _synthetic_ohlcv(60)
        trix, signal = compute_trix(df, period=9)
        assert len(trix) == len(df)
        assert len(signal) == len(df)

    def test_apo_crosses_zero_on_trend(self):
        df = _trending_ohlcv(60)
        apo = compute_apo(df, fast=10, slow=20)
        valid = apo.dropna()
        assert len(valid) > 0
        assert valid.iloc[-1] > valid.iloc[0]


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

    def test_cmo_mean_reversion_boundary(self):
        df = _mean_reverting_ohlcv(100)
        signals = CmoMeanReversionStrategy().generate_signals(df)
        assert set(signals.unique()).issubset({-1, 0, 1})

    def test_adx_trend_filter_signals(self):
        df = _trending_ohlcv(100)
        signals = AdxTrendFilterStrategy().generate_signals(df)
        assert set(signals.unique()).issubset({-1, 0, 1})
        assert (signals.dropna() == 1).any() or (signals.dropna() == 0).all()

    def test_vwap_band_mean_reversion_signals(self):
        df = _mean_reverting_ohlcv(100)
        signals = VwapBandMeanReversionStrategy().generate_signals(df)
        assert set(signals.unique()).issubset({-1, 0, 1})

    def test_cci_breakout_signals(self):
        df = _trending_ohlcv(100)
        signals = CciBreakoutStrategy().generate_signals(df)
        assert set(signals.unique()).issubset({-1, 0, 1})

    def test_trix_momentum_signals(self):
        df = _synthetic_ohlcv(100)
        signals = TrixMomentumStrategy().generate_signals(df)
        assert set(signals.unique()).issubset({-1, 0, 1})

    def test_apo_crossover_signals(self):
        df = _trending_ohlcv(100)
        signals = ApoCrossoverStrategy().generate_signals(df)
        assert set(signals.unique()).issubset({-1, 0, 1})

    def test_default_strategies_count(self):
        assert len(DEFAULT_STRATEGIES) == 10
        assert len(STRATEGY_REGISTRY) == 10
        assert len(build_default_strategies()) == 10


@pytest.mark.unit
class TestStrategyScoring:
    def test_run_strategy_on_frame_metrics(self):
        df = _synthetic_ohlcv(150)
        result = run_strategy_on_frame(df, EmaCrossoverStrategy())
        assert result.num_trades >= 0
        assert isinstance(result.net_profit_ratio, float)
        assert result.max_drawdown >= 0

    def test_optimize_selects_robust_multi_horizon_winner(self):
        df = _synthetic_ohlcv(150)

        def fake_fetch(symbol, end_date, lookback, **kwargs):
            return df

        with patch("tradingagents.backtest.engine.fetch_historical_crypto", side_effect=fake_fetch):
            opt = optimize_strategies("BTC/USDT", "2025-06-01")

        assert len(opt.results) == 30  # 10 strategies × 3 horizons
        assert opt.winner is not None
        assert opt.winner.lookback in ("24h", "7d")
        assert opt.winner.historical_profit_ratio > 0


@pytest.mark.unit
class TestPortfolio:
    def test_signals_to_intents_on_flip(self):
        df = _synthetic_ohlcv(10)
        signals = pd.Series([0, 0, 1, 1, -1, -1, 0, 0, 1, 1], index=df.index)
        intents = signals_to_intents(df, "BTC/USDT", signals)
        directions = [i.direction for i in intents]
        assert Direction.LONG in directions
        assert Direction.SHORT in directions
        assert Direction.EXIT in directions

    def test_virtual_portfolio_long_intent(self):
        portfolio = VirtualPortfolio(initial_equity=10_000.0)
        ts = datetime(2025, 1, 1, 12, 0)
        intent = TransactionIntent(
            timestamp=ts,
            asset="BTC/USDT",
            direction=Direction.LONG,
            leverage=1.0,
            sizing_pct=1.0,
        )
        portfolio.apply_intent(intent, fill_price=50_000.0)
        assert "BTC/USDT" in portfolio.positions
        assert portfolio.positions["BTC/USDT"]["side"] == 1

        portfolio.mark_to_market({"BTC/USDT": 55_000.0})
        assert portfolio.equity > 10_000.0

        snap = portfolio.snapshot(ts)
        assert snap.equity == portfolio.equity
        assert len(snap.positions) == 1

    def test_simulated_matcher_applies_slippage(self):
        matcher = SimulatedMatcher(slippage_bps=10.0)
        intent = TransactionIntent(
            timestamp=datetime.utcnow(),
            asset="ETH/USDT",
            direction=Direction.LONG,
        )
        fill = matcher.submit_intent(intent, reference_price=3_000.0)
        assert fill is not None
        assert fill.fill_price > 3_000.0
        assert len(matcher.fills) == 1


@pytest.mark.unit
class TestDummyFeed:
    def test_dummy_feed_mutates_price(self):
        feed = DummyPriceFeed(anchor_price=50_000.0, symbol="BTC/USDT", seed=1)
        p1 = feed.fetch_ticker()["last"]
        p2 = feed.fetch_ticker()["last"]
        assert p1 != p2
