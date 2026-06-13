"""Tests for activity log formatting and append-only buffer."""

from io import StringIO

import pytest
from rich.console import Console

from cli.activity_log import ActivityLog, is_live_display_tty
from tradingagents.backtest.schemas import StrategyMetrics, WinningStrategySummary
from tradingagents.simulator.activity_messages import (
    format_horizon_complete,
    format_horizon_skipped,
    format_price_feed,
    format_tick_action,
)


@pytest.mark.unit
class TestActivityMessages:
    def test_format_horizon_complete_includes_provider_and_best(self):
        metrics = [
            StrategyMetrics(
                strategy_name="ema_crossover",
                lookback="8h",
                parameters={},
                profit_factor=1.5,
                sharpe_ratio=0.8,
                max_drawdown=0.05,
                net_profit_ratio=0.12,
                num_trades=4,
                win_rate=75.0,
            ),
            StrategyMetrics(
                strategy_name="rsi_mean_reversion",
                lookback="8h",
                parameters={},
                profit_factor=2.1,
                sharpe_ratio=1.1,
                max_drawdown=0.03,
                net_profit_ratio=0.18,
                num_trades=6,
                win_rate=66.0,
            ),
        ]
        line = format_horizon_complete("8h", "CryptoCompare", 96, metrics)
        assert "CryptoCompare" in line
        assert "96 bars" in line
        assert "rsi_mean_reversion" in line
        assert "+18.00%" in line

    def test_format_horizon_skipped(self):
        line = format_horizon_skipped("24h", "insufficient bars (12 < 30)")
        assert "24h" in line
        assert "skipped" in line
        assert "insufficient" in line

    def test_format_tick_action_stop_loss(self):
        line = format_tick_action("stop_loss_exit", 49_500.0, 9_850.0)
        assert "STOP-LOSS" in line
        assert "49,500" in line
        assert "9,850" in line

    def test_format_price_feed(self):
        assert "Price feed" in format_price_feed("cryptocompare", 50_000.0, first=True)
        assert "Price source" in format_price_feed("coingecko", 50_000.0, first=False)


@pytest.mark.unit
class TestActivityLog:
    def test_append_caps_at_max_lines(self):
        log = ActivityLog(max_lines=3, enabled=True)
        log.append("one")
        log.append("two")
        log.append("three")
        log.append("four")
        assert log.line_count == 3
        panel = log.render_panel()
        buffer = StringIO()
        Console(file=buffer, width=120).print(panel)
        rendered = buffer.getvalue()
        assert "two" in rendered
        assert "four" in rendered
        assert "one" not in rendered

    def test_disabled_log_does_not_store(self):
        log = ActivityLog(enabled=False)
        log.append("hidden")
        assert log.line_count == 0

    def test_echo_callback(self):
        seen: list[str] = []
        log = ActivityLog(echo=seen.append)
        log.append("hello")
        assert seen == ["hello"]

    def test_is_live_display_tty_is_bool(self):
        assert isinstance(is_live_display_tty(), bool)

    def test_format_optimization_winner(self):
        winner = WinningStrategySummary(
            strategy_name="ema_crossover",
            lookback="24h",
            historical_profit_ratio=0.15,
            parameters={},
            profit_factor=1.8,
            sharpe_ratio=0.9,
            max_drawdown=0.04,
            num_trades=5,
        )
        from tradingagents.simulator.activity_messages import format_optimization_winner

        line = format_optimization_winner(winner)
        assert "ema_crossover" in line
        assert "24h" in line
