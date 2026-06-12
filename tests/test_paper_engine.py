"""Paper trading engine."""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.live_prices import LivePrice, PriceSource
from tradingagents.simulator import PaperTradingEngine, PaperTradingSession, StrategySignal


@pytest.mark.unit
class TestPaperTradingEngine:
    @patch("tradingagents.simulator.paper_engine.compute_strategy_signal", return_value="long")
    @patch("tradingagents.simulator.paper_engine.fetch_live_spot_price")
    def test_tick_updates_portfolio(self, mock_price, _signal):
        mock_price.return_value = LivePrice(
            symbol="BTC/USDT",
            price=50_000.0,
            source=PriceSource.CRYPTOCOMPARE,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.LONG,
            initial_equity=10_000.0,
        )
        engine = PaperTradingEngine(session, adaptive_enabled=False)
        result = engine.tick()
        assert result.price == pytest.approx(50_000.0, rel=1e-4)
        state = engine.get_state()
        assert state.symbol == "BTC/USDT"
        assert state.strategy_name == "ema_crossover"

    @patch("tradingagents.simulator.paper_engine.optimize_strategies")
    @patch("tradingagents.simulator.paper_engine.compute_strategy_signal", return_value="flat")
    @patch("tradingagents.simulator.paper_engine.fetch_live_spot_price")
    def test_adaptive_switch_on_rebacktest(self, mock_price, _signal, mock_optimize):
        from tradingagents.backtest.schemas import OptimizationResult, WinningStrategySummary

        mock_price.return_value = LivePrice(
            symbol="ETH/USDT",
            price=3_000.0,
            source=PriceSource.PLACEHOLDER,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        mock_optimize.return_value = OptimizationResult(
            symbol="ETH/USDT",
            end_date="2026-06-12",
            results=[],
            winner=WinningStrategySummary(
                strategy_name="rsi_mean_reversion",
                lookback="24h",
                historical_profit_ratio=0.1,
                parameters={"period": 14},
            ),
        )
        session = PaperTradingSession(
            symbol="ETH/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.FLAT,
            initial_equity=10_000.0,
        )
        engine = PaperTradingEngine(session, {"paper_loss_review_minutes": 0.01, "paper_loss_threshold_pct": 1.0})
        engine._adaptive.record_equity(9_800.0)
        engine._adaptive.record_equity(9_700.0)
        switch_cb = MagicMock()
        engine.on_strategy_switch = switch_cb
        engine._run_adaptive_rebacktest(
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        )
        assert session.strategy_name == "rsi_mean_reversion"
        switch_cb.assert_called_once_with("ema_crossover", "rsi_mean_reversion")
