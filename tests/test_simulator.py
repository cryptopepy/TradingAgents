"""Paper-trading simulator tick evaluation."""

import pytest

from tradingagents.backtest.portfolio import VirtualPortfolio
from tradingagents.simulator.core import (
    StrategySignal,
    evaluate_live_market_tick,
)


@pytest.mark.unit
class TestEvaluateLiveMarketTick:
    def test_enter_long_on_signal(self):
        portfolio = VirtualPortfolio(initial_equity=1.0)
        result = evaluate_live_market_tick(
            portfolio,
            100.0,
            StrategySignal.LONG,
            asset="BTC/USDT",
            stop_loss_pct=0.05,
        )
        assert result.action_taken == "enter_long"
        assert "BTC/USDT" in portfolio.positions

    def test_stop_loss_triggers_exit(self):
        portfolio = VirtualPortfolio(initial_equity=1.0)
        evaluate_live_market_tick(
            portfolio,
            100.0,
            StrategySignal.LONG,
            asset="ETH/USDT",
            stop_loss_pct=0.02,
        )
        result = evaluate_live_market_tick(
            portfolio,
            97.0,
            StrategySignal.LONG,
            asset="ETH/USDT",
            stop_loss_pct=0.02,
        )
        assert result.stop_loss_triggered is True
        assert result.action_taken == "stop_loss_exit"
        assert "ETH/USDT" not in portfolio.positions

    def test_flat_signal_exits_position(self):
        portfolio = VirtualPortfolio(initial_equity=1.0)
        evaluate_live_market_tick(
            portfolio,
            50.0,
            StrategySignal.SHORT,
            asset="SOL/USDT",
            stop_loss_pct=0.1,
        )
        result = evaluate_live_market_tick(
            portfolio,
            49.0,
            StrategySignal.FLAT,
            asset="SOL/USDT",
            stop_loss_pct=0.1,
        )
        assert result.action_taken == "signal_exit"
        assert "SOL/USDT" not in portfolio.positions
