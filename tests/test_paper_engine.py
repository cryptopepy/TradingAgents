"""Paper trading engine."""

import threading
import time
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

    @patch("tradingagents.simulator.paper_engine.compute_strategy_signal", return_value="flat")
    @patch("tradingagents.simulator.paper_engine.fetch_live_spot_price")
    def test_run_loop_stops_promptly_during_sleep(self, mock_price, _signal):
        mock_price.return_value = LivePrice(
            symbol="BTC/USDT",
            price=50_000.0,
            source=PriceSource.CRYPTOCOMPARE,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.FLAT,
            initial_equity=10_000.0,
        )
        engine = PaperTradingEngine(session, adaptive_enabled=False)
        tick_count = 0

        def _tick_and_schedule_stop():
            nonlocal tick_count
            tick_count += 1
            if tick_count == 1:
                threading.Timer(0.1, engine.stop).start()
            return MagicMock()

        with patch.object(engine, "tick", side_effect=_tick_and_schedule_stop):
            start = time.monotonic()
            engine.run_loop(interval_seconds=5.0)
            elapsed = time.monotonic() - start

        assert tick_count == 1
        assert elapsed < 2.0

    @patch("tradingagents.simulator.paper_engine.compute_strategy_signal", return_value="flat")
    @patch("tradingagents.simulator.paper_engine.fetch_live_spot_price")
    def test_state_includes_last_drawdown_review(self, mock_price, _signal):
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        mock_price.return_value = LivePrice(
            symbol="BTC/USDT",
            price=50_000.0,
            source=PriceSource.CRYPTOCOMPARE,
            timestamp=now,
        )
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.FLAT,
            initial_equity=10_000.0,
        )
        engine = PaperTradingEngine(session, adaptive_enabled=True)
        engine._adaptive.note_drawdown_review(now - timedelta(minutes=12))
        state = engine.get_state()

        assert state.last_drawdown_review == "12m ago"
        assert state.effective_drawdown_window_minutes == pytest.approx(60.0)

    def test_fresh_start_ignores_saved_session(self, tmp_path):
        from tradingagents.simulator.persistence import save_paper_session

        config = {
            "data_cache_dir": str(tmp_path),
            "paper_fresh_start": True,
        }
        portfolio = __import__(
            "tradingagents.backtest.portfolio", fromlist=["VirtualPortfolio"]
        ).VirtualPortfolio(initial_equity=10_000.0)
        portfolio.equity = 15_432.0
        save_paper_session(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            lookback="24h",
            signal="long",
            portfolio=portfolio,
            config=config,
        )
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.FLAT,
            initial_equity=10_000.0,
        )
        engine = PaperTradingEngine(session, config, adaptive_enabled=False)
        assert engine.portfolio.equity == pytest.approx(10_000.0)
