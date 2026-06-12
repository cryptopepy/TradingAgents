"""Post-analysis menu wiring (mocked — no interactive CLI)."""

from unittest.mock import MagicMock, patch

import pytest

from cli.post_analysis import (
    _rank_strategy_rows,
    render_optimization_table,
    run_interactive_backtest,
    show_post_analysis_menu,
)
from tradingagents.backtest.schemas import OptimizationResult, StrategyMetrics, WinningStrategySummary


def _sample_optimization() -> OptimizationResult:
    metrics = [
        StrategyMetrics(
            strategy_name="EMA Cross",
            lookback="24h",
            profit_factor=1.5,
            max_drawdown=0.08,
            net_profit_ratio=0.12,
        ),
        StrategyMetrics(
            strategy_name="RSI Mean Reversion",
            lookback="7d",
            profit_factor=2.1,
            max_drawdown=0.05,
            net_profit_ratio=0.18,
        ),
    ]
    winner = WinningStrategySummary(
        strategy_name="RSI Mean Reversion",
        lookback="7d",
        historical_profit_ratio=0.18,
        profit_factor=2.1,
        max_drawdown=0.05,
    )
    return OptimizationResult(
        symbol="BTC/USDT",
        end_date="2026-06-11",
        results=metrics,
        winner=winner,
    )


@pytest.mark.unit
class TestPostAnalysisMenu:
    def test_rank_strategy_rows_puts_winner_first(self):
        metrics = _sample_optimization().results
        ranked = _rank_strategy_rows(metrics, "RSI Mean Reversion")
        assert ranked[0].strategy_name == "RSI Mean Reversion"

    def test_render_optimization_table_marks_winner(self):
        from io import StringIO

        from rich.console import Console

        table = render_optimization_table(_sample_optimization())
        buf = StringIO()
        Console(file=buf, width=120).print(table)
        rendered = buf.getvalue()
        assert "RSI Mean Reversion" in rendered
        assert "WINNER" in rendered

    @patch("cli.post_analysis.questionary.confirm")
    @patch("cli.post_analysis.run_backtest_with_progress")
    @patch("cli.post_analysis.deploy_winning_strategy")
    def test_run_interactive_backtest_skips_deploy_when_declined(
        self, mock_deploy, mock_backtest, mock_confirm
    ):
        opt = _sample_optimization()
        mock_backtest.return_value = opt
        mock_deploy.return_value = opt
        mock_confirm.return_value = MagicMock(ask=lambda: False)

        result = run_interactive_backtest("BTC/USDT", "2026-06-11", {})
        assert result is not None
        mock_backtest.assert_called_once()

    @patch("cli.post_analysis.questionary.select")
    def test_show_post_analysis_menu_exit(self, mock_select):
        mock_select.return_value = MagicMock(ask=lambda: "exit")
        action = show_post_analysis_menu("ETH/USDT", "2026-06-11", {}, no_backtest=True)
        assert action == "exit"

    @patch("cli.post_analysis.questionary.select")
    def test_no_backtest_hides_backtest_options(self, mock_select):
        mock_select.return_value = MagicMock(ask=lambda: "exit")
        show_post_analysis_menu("ETH/USDT", "2026-06-11", {}, no_backtest=True)
        choices = mock_select.call_args.kwargs["choices"]
        values = [c.value for c in choices]
        assert "auto_backtest" not in values
        assert "custom_backtest" not in values
