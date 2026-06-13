"""Paper trading keyboard controls and close-position behavior."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from cli.keyboard_input import poll_stdin_key
from cli.paper_display import PaperDisplayContext
from cli.paper_trading import MOVERS_CONTROLS_TEXT, PAPER_CONTROLS_TEXT, render_paper_live_display
from tradingagents.dataflows.live_prices import LivePrice, PriceSource
from tradingagents.simulator import PaperTradingEngine, PaperTradingSession, StrategySignal
from tradingagents.simulator.core import _sleep_until_stopped_or_key


@pytest.mark.unit
class TestKeyboardInput:
    def test_poll_stdin_key_returns_none_when_not_tty(self):
        with patch("cli.keyboard_input.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            assert poll_stdin_key(0.1) is None


@pytest.mark.unit
class TestPaperControlsDisplay:
    def test_live_display_includes_controls_footer(self):
        from datetime import datetime, timezone

        from tradingagents.simulator.paper_engine import PaperTradingState

        state = PaperTradingState(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            lookback="24h",
            signal="flat",
            equity=10_000.0,
            cash=10_000.0,
            initial_equity=10_000.0,
            pnl=0.0,
            pnl_pct=0.0,
            price=50_000.0,
            price_source="placeholder",
            drawdown_pct=0.0,
            rebacktest_count=0,
            timestamp=datetime.now(timezone.utc),
        )
        buffer = StringIO()
        Console(file=buffer, width=120).print(render_paper_live_display(state))
        rendered = buffer.getvalue()
        assert PAPER_CONTROLS_TEXT in rendered
        assert "(m) movers" in rendered
        assert "(c)" in rendered
        assert "(r)" in rendered
        assert "(q)" in rendered
        assert "Ctrl+C" not in rendered

    def test_movers_overlay_shows_movers_controls(self):
        from datetime import datetime, timezone

        from cli.movers_board import MoversBoard
        from tradingagents.dataflows.market_movers import MarketMover, MoversSnapshot
        from tradingagents.simulator.paper_engine import PaperTradingState

        state = PaperTradingState(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            lookback="24h",
            signal="flat",
            equity=10_000.0,
            cash=10_000.0,
            initial_equity=10_000.0,
            pnl=0.0,
            pnl_pct=0.0,
            price=50_000.0,
            price_source="placeholder",
            drawdown_pct=0.0,
            rebacktest_count=0,
            timestamp=datetime.now(timezone.utc),
        )
        board = MoversBoard({})
        board._snapshot = MoversSnapshot(
            gainers=(
                MarketMover(
                    rank=1,
                    symbol="BTC",
                    pair="BTC/USDT",
                    name="BTC",
                    change_pct=1.2,
                    volume_usd=1_000_000.0,
                    price_usd=50_000.0,
                    side="gainer",
                ),
            ),
            losers=(),
            fetched_at=datetime.now(timezone.utc),
            source="kraken",
        )
        ctx = PaperDisplayContext(show_movers=True)
        buffer = StringIO()
        Console(file=buffer, width=120).print(
            render_paper_live_display(state, display_ctx=ctx, movers_board=board)
        )
        rendered = buffer.getvalue()
        assert MOVERS_CONTROLS_TEXT in rendered
        assert "Kraken movers" in rendered


@pytest.mark.unit
class TestCloseOpenPosition:
    @patch("tradingagents.simulator.paper_engine.optimize_strategies")
    @patch("tradingagents.simulator.paper_engine.compute_strategy_signal", return_value="long")
    @patch("tradingagents.simulator.paper_engine.fetch_live_spot_price")
    def test_close_open_position_realizes_pnl_and_reoptimizes(
        self, mock_price, _signal, mock_optimize
    ):
        from tradingagents.backtest.schemas import OptimizationResult, WinningStrategySummary

        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        mock_price.return_value = LivePrice(
            symbol="BTC/USDT",
            price=55_000.0,
            source=PriceSource.CRYPTOCOMPARE,
            timestamp=now,
        )
        mock_optimize.return_value = OptimizationResult(
            symbol="BTC/USDT",
            end_date="2026-06-12",
            results=[],
            winner=WinningStrategySummary(
                strategy_name="rsi_mean_reversion",
                lookback="24h",
                historical_profit_ratio=0.1,
                parameters={"period": 14},
            ),
            deployable=True,
        )
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.LONG,
            initial_equity=10_000.0,
        )
        engine = PaperTradingEngine(
            session,
            {"paper_fresh_start": True, "paper_state_persistence": False},
            adaptive_enabled=True,
        )
        engine.tick()
        assert "BTC/USDT" in engine.portfolio.positions

        state_cb = MagicMock()
        engine.on_state_change = state_cb
        closed = engine.close_open_position(reoptimize=True)

        assert closed is True
        assert "BTC/USDT" not in engine.portfolio.positions
        assert session.strategy_name == "rsi_mean_reversion"
        mock_optimize.assert_called_once()
        state_cb.assert_called_once()

    @patch("tradingagents.simulator.paper_engine.fetch_live_spot_price")
    def test_close_open_position_noop_when_flat(self, mock_price):
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
        engine = PaperTradingEngine(
            session,
            {"paper_fresh_start": True, "paper_state_persistence": False},
            adaptive_enabled=False,
        )
        assert engine.close_open_position() is False


@pytest.mark.unit
class TestRunLoopKeyboard:
    @patch("tradingagents.simulator.paper_engine.compute_strategy_signal", return_value="flat")
    @patch("tradingagents.simulator.paper_engine.fetch_live_spot_price")
    def test_run_loop_quits_on_q_key(self, mock_price, _signal):
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
        poll_calls = 0

        def _poll_key(_timeout: float):
            nonlocal poll_calls
            poll_calls += 1
            if poll_calls == 1:
                return "q"
            return None

        engine.run_loop(interval_seconds=5.0, poll_key=_poll_key)
        assert engine._stop_event.is_set()
        assert poll_calls == 1

    @patch("tradingagents.simulator.paper_engine.optimize_strategies")
    @patch("tradingagents.simulator.paper_engine.compute_strategy_signal", return_value="long")
    @patch("tradingagents.simulator.paper_engine.fetch_live_spot_price")
    def test_run_loop_closes_position_on_c_key(self, mock_price, _signal, mock_optimize):
        from tradingagents.backtest.schemas import OptimizationResult, WinningStrategySummary

        mock_price.return_value = LivePrice(
            symbol="BTC/USDT",
            price=50_000.0,
            source=PriceSource.CRYPTOCOMPARE,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        mock_optimize.return_value = OptimizationResult(
            symbol="BTC/USDT",
            end_date="2026-06-12",
            results=[],
            winner=WinningStrategySummary(
                strategy_name="rsi_mean_reversion",
                lookback="24h",
                historical_profit_ratio=0.1,
                parameters={"period": 14},
            ),
            deployable=True,
        )
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.LONG,
            initial_equity=10_000.0,
        )
        engine = PaperTradingEngine(
            session,
            {"paper_fresh_start": True, "paper_state_persistence": False},
            adaptive_enabled=True,
        )
        close_mock = MagicMock(wraps=engine.close_open_position)

        with patch.object(engine, "close_open_position", close_mock):
            poll_calls = 0

            def _poll_key(_timeout: float):
                nonlocal poll_calls
                poll_calls += 1
                if poll_calls == 1:
                    return "c"
                if poll_calls == 2:
                    return "q"
                return None

            engine.run_loop(interval_seconds=5.0, poll_key=_poll_key)

        close_mock.assert_called_once_with(reoptimize=True)

    @patch("tradingagents.simulator.paper_engine.optimize_strategies")
    @patch("tradingagents.simulator.paper_engine.compute_strategy_signal", return_value="flat")
    @patch("tradingagents.simulator.paper_engine.fetch_live_spot_price")
    def test_run_loop_reanalyzes_on_r_key(self, mock_price, _signal, mock_optimize):
        from tradingagents.backtest.schemas import OptimizationResult, WinningStrategySummary

        mock_price.return_value = LivePrice(
            symbol="BTC/USDT",
            price=50_000.0,
            source=PriceSource.CRYPTOCOMPARE,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        mock_optimize.return_value = OptimizationResult(
            symbol="BTC/USDT",
            end_date="2026-06-12",
            results=[],
            winner=WinningStrategySummary(
                strategy_name="rsi_mean_reversion",
                lookback="24h",
                historical_profit_ratio=0.1,
                parameters={"period": 14},
            ),
            deployable=True,
        )
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.FLAT,
            initial_equity=10_000.0,
        )
        engine = PaperTradingEngine(
            session,
            {"paper_fresh_start": True, "paper_state_persistence": False},
            adaptive_enabled=True,
        )
        reanalyze_mock = MagicMock(wraps=engine.reanalyze)

        with patch.object(engine, "reanalyze", reanalyze_mock):
            poll_calls = 0

            def _poll_key(_timeout: float):
                nonlocal poll_calls
                poll_calls += 1
                if poll_calls == 1:
                    return "r"
                if poll_calls == 2:
                    return "q"
                return None

            engine.run_loop(interval_seconds=5.0, poll_key=_poll_key)

        reanalyze_mock.assert_called_once()

    def test_sleep_until_stopped_or_key_returns_pressed_key(self):
        import threading

        stop_event = threading.Event()
        calls = 0

        def _poll(timeout: float):
            nonlocal calls
            calls += 1
            return "q" if calls == 2 else None

        key = _sleep_until_stopped_or_key(stop_event, 1.0, _poll)
        assert key == "q"
        assert calls >= 2
