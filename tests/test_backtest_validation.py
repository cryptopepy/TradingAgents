"""Backtest validation and interactive parameter resolution."""

from unittest.mock import MagicMock, patch

import pytest

from cli.backtest_interactive import resolve_backtest_params
from tradingagents.backtest.schemas import OptimizationResult
from tradingagents.backtest.validation import (
    BacktestValidationError,
    require_optimization_results,
    validate_end_date,
    validate_ticker,
)


@pytest.mark.unit
class TestBacktestValidation:
    def test_validate_ticker_normalizes_pair(self):
        assert validate_ticker("btc-usdt") == "BTC/USDT"

    def test_validate_ticker_rejects_empty(self):
        with pytest.raises(BacktestValidationError, match="Ticker is required"):
            validate_ticker("")

    def test_validate_end_date_rejects_future(self):
        with pytest.raises(BacktestValidationError, match="future"):
            validate_end_date("2099-12-31")

    def test_require_optimization_results_raises_with_diagnostics(self):
        result = OptimizationResult(
            symbol="BTC/USDT",
            end_date="2026-06-01",
            results=[],
            warnings=["8h: historic fetch failed — timeout"],
        )
        with pytest.raises(BacktestValidationError, match="no strategy metrics"):
            require_optimization_results(result)

    def test_resolve_backtest_params_non_interactive_defaults(self):
        params = resolve_backtest_params(
            ticker=None,
            end_date=None,
            interactive=False,
        )
        assert params.ticker == "BTC/USDT"
        assert params.stop_loss_pct == 0.02
        assert params.initial_equity == 10_000.0

    @patch("cli.backtest_interactive._is_interactive_tty", return_value=False)
    def test_resolve_backtest_params_requires_tty_for_interactive(self, _tty):
        with pytest.raises(BacktestValidationError, match="TTY"):
            resolve_backtest_params(ticker=None, end_date=None, interactive=True)

    @patch("cli.backtest_interactive._is_interactive_tty", return_value=True)
    @patch("cli.backtest_interactive.questionary.confirm")
    @patch("cli.backtest_interactive.questionary.text")
    @patch("cli.backtest_interactive.questionary.select")
    def test_prompt_backtest_params_via_resolve(
        self, mock_select, mock_text, mock_confirm, _tty
    ):
        mock_select.return_value = MagicMock(ask=lambda: "all")
        mock_text.side_effect = [
            MagicMock(ask=lambda: "ETH/USDC"),
            MagicMock(ask=lambda: "2026-06-01"),
            MagicMock(ask=lambda: "0.02"),
            MagicMock(ask=lambda: "0.001"),
            MagicMock(ask=lambda: "25000"),
        ]
        mock_confirm.return_value = MagicMock(ask=lambda: False)

        params = resolve_backtest_params(ticker=None, end_date=None, interactive=True)
        assert params.ticker == "ETH/USDC"
        assert params.end_date == "2026-06-01"
        assert params.initial_equity == 25_000.0
