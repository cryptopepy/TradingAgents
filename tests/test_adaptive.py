"""Adaptive strategy monitor."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tradingagents.simulator.adaptive import AdaptiveStrategyMonitor


@pytest.mark.unit
class TestAdaptiveStrategyMonitor:
    def test_no_rebacktest_when_equity_stable(self):
        monitor = AdaptiveStrategyMonitor(
            loss_review_minutes=30,
            loss_threshold_pct=5.0,
            initial_equity=10_000.0,
        )
        now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        monitor.record_equity(10_000.0, now)
        monitor.record_equity(9_900.0, now + timedelta(minutes=10))
        assert monitor.should_rebacktest(now + timedelta(minutes=10)) is False

    def test_rebacktest_after_sustained_drawdown(self):
        monitor = AdaptiveStrategyMonitor(
            loss_review_minutes=30,
            loss_threshold_pct=5.0,
            initial_equity=10_000.0,
        )
        start = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        monitor.record_equity(10_000.0, start)
        monitor.record_equity(9_400.0, start + timedelta(minutes=5))
        assert monitor.should_rebacktest(start + timedelta(minutes=20)) is False
        assert monitor.should_rebacktest(start + timedelta(minutes=35)) is True

    def test_mark_rebacktest_resets_timer(self):
        monitor = AdaptiveStrategyMonitor(
            loss_review_minutes=10,
            loss_threshold_pct=5.0,
            initial_equity=10_000.0,
        )
        now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        monitor.record_equity(9_000.0, now)
        assert monitor.should_rebacktest(now + timedelta(minutes=15)) is True
        monitor.mark_rebacktest_done()
        assert monitor.should_rebacktest(now + timedelta(minutes=15)) is False
        assert monitor.rebacktest_count == 1


@pytest.mark.unit
class TestAutonomousRotationLog:
    @patch("tradingagents.simulator.paper_engine.optimize_strategies")
    @patch("tradingagents.simulator.paper_engine.compute_strategy_signal", return_value="flat")
    @patch("tradingagents.simulator.paper_engine.fetch_live_spot_price")
    def test_rotation_log_written(self, mock_price, _signal, mock_optimize, tmp_path):
        from datetime import datetime, timezone

        from tradingagents.backtest.schemas import OptimizationResult, WinningStrategySummary
        from tradingagents.dataflows.live_prices import LivePrice, PriceSource
        from tradingagents.simulator import PaperTradingEngine, PaperTradingSession, StrategySignal

        mock_price.return_value = LivePrice(
            symbol="BTC/USDT",
            price=50_000.0,
            source=PriceSource.PLACEHOLDER,
            timestamp=datetime.now(timezone.utc),
        )
        mock_optimize.return_value = OptimizationResult(
            symbol="BTC/USDT",
            end_date="2026-06-12",
            results=[],
            winner=WinningStrategySummary(
                strategy_name="trix_momentum",
                lookback="8h",
                historical_profit_ratio=0.05,
            ),
        )
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.FLAT,
            initial_equity=10_000.0,
        )
        config = {
            "results_dir": str(tmp_path),
            "paper_state_persistence": False,
        }
        engine = PaperTradingEngine(session, config)
        engine._log_autonomous_rotation("ema_crossover", "trix_momentum")
        log_file = tmp_path / "paper_rotation.log"
        assert log_file.exists()
        assert "[AUTONOMOUS ROTATION]" in log_file.read_text(encoding="utf-8")
