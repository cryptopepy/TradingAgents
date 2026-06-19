"""Paper trading CLI parameter resolution and validation."""

from unittest.mock import MagicMock, patch

import pytest

from cli.paper_interactive import (
    resolve_paper_params,
    validate_strategy_name,
    validate_ticks,
)
from tradingagents.backtest.validation import BacktestValidationError


@pytest.mark.unit
class TestPaperInteractive:
    def test_validate_strategy_name_accepts_registry(self):
        assert validate_strategy_name("ema_crossover") == "ema_crossover"

    def test_validate_strategy_name_auto_is_none(self):
        assert validate_strategy_name(None) is None

    def test_validate_strategy_name_rejects_unknown(self):
        with pytest.raises(BacktestValidationError, match="Unknown strategy"):
            validate_strategy_name("not_a_strategy")

    def test_validate_ticks_rejects_non_positive(self):
        with pytest.raises(BacktestValidationError, match="positive integer"):
            validate_ticks(0)

    def test_resolve_paper_params_non_interactive_defaults(self, tmp_path):
        params = resolve_paper_params(
            ticker=None,
            strategy_name=None,
            equity=None,
            ticks=None,
            live_mode=False,
            adaptive_enabled=None,
            interactive=False,
            config={"data_cache_dir": str(tmp_path)},
        )
        assert params.ticker == "BTC/USDT"
        assert params.initial_equity == 10_000.0
        assert params.strategy_name is None
        assert params.stop_loss_pct == 0.02
        assert params.take_profit_pct is None
        assert params.adaptive_enabled is True

    def test_resolve_paper_params_non_interactive_explicit_flags(self):
        params = resolve_paper_params(
            ticker="eth/usdc",
            strategy_name="rsi_mean_reversion",
            equity=5000.0,
            ticks=20,
            live_mode=True,
            adaptive_enabled=False,
            interactive=False,
        )
        assert params.ticker == "ETH/USDC"
        assert params.strategy_name == "rsi_mean_reversion"
        assert params.initial_equity == 5000.0
        assert params.ticks == 20
        assert params.live_mode is True
        assert params.adaptive_enabled is False

    @patch("cli.paper_interactive._is_interactive_tty", return_value=False)
    def test_resolve_paper_params_requires_tty_for_interactive(self, _tty):
        with pytest.raises(BacktestValidationError, match="TTY"):
            resolve_paper_params(
                ticker=None,
                strategy_name=None,
                equity=None,
                ticks=None,
                live_mode=False,
                adaptive_enabled=None,
                interactive=True,
            )

    @patch("cli.paper_interactive._saved_session_equity", return_value=None)
    @patch("cli.paper_interactive._is_interactive_tty", return_value=True)
    @patch("cli.paper_interactive.questionary.confirm")
    @patch("cli.paper_interactive.questionary.text")
    @patch("cli.paper_interactive.questionary.select")
    def test_prompt_paper_params_via_resolve(
        self, mock_select, mock_text, mock_confirm, _tty, _saved
    ):
        mock_select.return_value = MagicMock(ask=lambda: "__auto_backtest__")
        mock_text.side_effect = [
            MagicMock(ask=lambda: "ETH/USDC"),
            MagicMock(ask=lambda: "10000"),
            MagicMock(ask=lambda: "10"),
            MagicMock(ask=lambda: "0.03"),
            MagicMock(ask=lambda: "0.06"),
            MagicMock(ask=lambda: "30"),
            MagicMock(ask=lambda: "5.0"),
        ]
        mock_confirm.side_effect = [
            MagicMock(ask=lambda: True),
            MagicMock(ask=lambda: True),
            MagicMock(ask=lambda: True),
            MagicMock(ask=lambda: True),
        ]

        params = resolve_paper_params(
            ticker=None,
            strategy_name=None,
            equity=None,
            ticks=None,
            live_mode=False,
            adaptive_enabled=None,
            interactive=True,
        )
        assert params.ticker == "ETH/USDC"
        assert params.strategy_name is None
        assert params.initial_equity == 10_000.0
        assert params.ticks == 10
        assert params.stop_loss_pct == 0.03
        assert params.take_profit_pct == 0.06
        assert params.live_mode is True
        assert params.adaptive_enabled is True
        assert params.spike_review_enabled is True
        assert params.spike_intelligent_tuning is True
        assert params.drawdown_window_minutes == 30.0
        assert params.max_drawdown_pct == 5.0

    def test_resolve_paper_params_fresh_start_skips_resume(self, tmp_path):
        from tradingagents.simulator.persistence import save_paper_session
        from tradingagents.backtest.portfolio import VirtualPortfolio

        config = {"data_cache_dir": str(tmp_path)}
        portfolio = VirtualPortfolio(initial_equity=10_000.0)
        portfolio.equity = 15_432.0
        save_paper_session(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            lookback="24h",
            signal="long",
            portfolio=portfolio,
            config=config,
        )

        params = resolve_paper_params(
            ticker="BTC/USDT",
            strategy_name="ema_crossover",
            equity=10_000.0,
            ticks=5,
            live_mode=False,
            adaptive_enabled=False,
            interactive=False,
            fresh_start=True,
            config=config,
        )
        assert params.fresh_start is True
        assert params.resume_saved_session is False

    def test_resolve_paper_params_non_interactive_resumes_saved_session(self, tmp_path):
        from tradingagents.simulator.persistence import save_paper_session
        from tradingagents.backtest.portfolio import VirtualPortfolio

        config = {"data_cache_dir": str(tmp_path)}
        portfolio = VirtualPortfolio(initial_equity=10_000.0)
        portfolio.equity = 15_432.0
        save_paper_session(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            lookback="24h",
            signal="long",
            portfolio=portfolio,
            config=config,
        )

        params = resolve_paper_params(
            ticker="BTC/USDT",
            strategy_name="ema_crossover",
            equity=10_000.0,
            ticks=5,
            live_mode=False,
            adaptive_enabled=False,
            interactive=False,
            fresh_start=False,
            config=config,
        )
        assert params.resume_saved_session is True
        assert params.fresh_start is False
        assert params.initial_equity == 15_432.0

    @patch("cli.paper_interactive._saved_session_equity", return_value=15_432.0)
    @patch("cli.paper_interactive._is_interactive_tty", return_value=True)
    @patch("cli.paper_interactive.questionary.confirm")
    @patch("cli.paper_interactive.questionary.text")
    @patch("cli.paper_interactive.questionary.select")
    def test_prompt_resume_saved_session(
        self, mock_select, mock_text, mock_confirm, _tty, _saved
    ):
        mock_select.side_effect = [
            MagicMock(ask=lambda: "__auto_backtest__"),
            MagicMock(ask=lambda: True),
        ]
        mock_text.side_effect = [
            MagicMock(ask=lambda: "BTC/USDT"),
            MagicMock(ask=lambda: "10"),
            MagicMock(ask=lambda: "0.02"),
            MagicMock(ask=lambda: ""),
            MagicMock(ask=lambda: "60"),
            MagicMock(ask=lambda: "5.0"),
        ]
        mock_confirm.side_effect = [
            MagicMock(ask=lambda: False),
            MagicMock(ask=lambda: True),
            MagicMock(ask=lambda: True),
            MagicMock(ask=lambda: True),
        ]

        params = resolve_paper_params(
            ticker=None,
            strategy_name=None,
            equity=None,
            ticks=None,
            live_mode=False,
            adaptive_enabled=None,
            interactive=True,
        )
        assert params.resume_saved_session is True
        assert params.fresh_start is False
        assert params.initial_equity == 15_432.0

    @patch("cli.paper_interactive.delete_paper_session")
    @patch("cli.paper_interactive._saved_session_equity", return_value=15_432.0)
    @patch("cli.paper_interactive._is_interactive_tty", return_value=True)
    @patch("cli.paper_interactive.questionary.confirm")
    @patch("cli.paper_interactive.questionary.text")
    @patch("cli.paper_interactive.questionary.select")
    def test_prompt_fresh_start_clears_session_then_equity(
        self, mock_select, mock_text, mock_confirm, _tty, _saved, mock_delete
    ):
        mock_select.side_effect = [
            MagicMock(ask=lambda: "__auto_backtest__"),
            MagicMock(ask=lambda: False),
        ]
        mock_text.side_effect = [
            MagicMock(ask=lambda: "BTC/USDT"),
            MagicMock(ask=lambda: "12000"),
            MagicMock(ask=lambda: "5"),
            MagicMock(ask=lambda: "0.02"),
            MagicMock(ask=lambda: ""),
            MagicMock(ask=lambda: "60"),
            MagicMock(ask=lambda: "5.0"),
        ]
        mock_confirm.side_effect = [
            MagicMock(ask=lambda: False),
            MagicMock(ask=lambda: True),
            MagicMock(ask=lambda: True),
            MagicMock(ask=lambda: True),
        ]

        params = resolve_paper_params(
            ticker=None,
            strategy_name=None,
            equity=None,
            ticks=None,
            live_mode=False,
            adaptive_enabled=None,
            interactive=True,
        )
        mock_delete.assert_called_once()
        assert params.resume_saved_session is False
        assert params.fresh_start is True
        assert params.initial_equity == 12_000.0
