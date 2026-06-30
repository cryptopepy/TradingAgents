"""Paper trading leverage — portfolio, tick evaluation, and engine integration."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tradingagents.backtest.portfolio import Direction, TransactionIntent, VirtualPortfolio
from tradingagents.dataflows.live_prices import LivePrice, PriceSource
from tradingagents.simulator import PaperTradingEngine, PaperTradingSession, StrategySignal
from tradingagents.simulator.core import evaluate_live_market_tick


def _long_entry(
    portfolio: VirtualPortfolio,
    *,
    price: float,
    leverage: float,
    equity: float = 10_000.0,
    fee_bps: float = 0.0,
) -> None:
    portfolio.fee_bps = fee_bps
    portfolio.initial_equity = equity
    portfolio.cash = equity
    portfolio.equity = equity
    portfolio.apply_intent(
        TransactionIntent(
            timestamp=datetime(2025, 6, 1, 12, 0),
            asset="BTC/USDT",
            direction=Direction.LONG,
            leverage=leverage,
            sizing_pct=1.0,
        ),
        fill_price=price,
    )


@pytest.mark.unit
class TestVirtualPortfolioLeverage:
    def test_leverage_doubles_pnl_on_one_percent_move(self):
        portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
        _long_entry(portfolio, price=50_000.0, leverage=2.0)
        portfolio.mark_to_market({"BTC/USDT": 50_500.0})  # +1%
        assert portfolio.equity == pytest.approx(10_200.0, rel=1e-4)

    def test_leverage_triples_pnl_on_one_percent_move(self):
        portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
        _long_entry(portfolio, price=50_000.0, leverage=3.0)
        portfolio.mark_to_market({"BTC/USDT": 50_500.0})  # +1%
        assert portfolio.equity == pytest.approx(10_300.0, rel=1e-4)

    def test_leverage_scales_realized_pnl_on_close(self):
        portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
        _long_entry(portfolio, price=50_000.0, leverage=2.0)
        portfolio.apply_intent(
            TransactionIntent(
                timestamp=datetime(2025, 6, 2, 12, 0),
                asset="BTC/USDT",
                direction=Direction.EXIT,
            ),
            fill_price=55_000.0,  # +10% price
        )
        # 10% × 2x notional ≈ +20% on equity
        assert portfolio.equity == pytest.approx(12_000.0, rel=1e-4)

    def test_margin_used_reflects_leverage(self):
        portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
        _long_entry(portfolio, price=50_000.0, leverage=2.0)
        # notional 20k / 2x = 10k margin
        assert portfolio.margin_used == pytest.approx(10_000.0, rel=1e-4)


@pytest.mark.unit
class TestEvaluateLiveMarketTickLeverage:
    def test_leverage_passed_to_position_notional(self):
        portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
        evaluate_live_market_tick(
            portfolio,
            50_000.0,
            StrategySignal.LONG,
            asset="BTC/USDT",
            slippage_bps=0.0,
            leverage=3.0,
        )
        pos = portfolio.positions["BTC/USDT"]
        assert pos["leverage"] == pytest.approx(3.0)
        assert pos["size"] * pos["entry_price"] == pytest.approx(30_000.0, rel=1e-4)

    def test_leverage_scales_unrealized_equity_on_hold(self):
        portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
        evaluate_live_market_tick(
            portfolio,
            50_000.0,
            StrategySignal.LONG,
            asset="BTC/USDT",
            slippage_bps=0.0,
            leverage=2.0,
        )
        result = evaluate_live_market_tick(
            portfolio,
            50_500.0,
            StrategySignal.LONG,
            asset="BTC/USDT",
            slippage_bps=0.0,
            leverage=2.0,
        )
        assert result.action_taken == "hold"
        assert result.portfolio_equity == pytest.approx(10_200.0, rel=1e-4)

    def test_stop_loss_uses_price_move_not_leveraged_equity(self):
        """SL/TP thresholds are % of underlying price, not leveraged equity PnL."""
        portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
        evaluate_live_market_tick(
            portfolio,
            50_000.0,
            StrategySignal.LONG,
            asset="BTC/USDT",
            slippage_bps=0.0,
            leverage=3.0,
            stop_loss_pct=0.02,
        )
        # -2% price triggers SL even though equity loss is ~6%
        result = evaluate_live_market_tick(
            portfolio,
            49_000.0,
            StrategySignal.LONG,
            asset="BTC/USDT",
            slippage_bps=0.0,
            leverage=3.0,
            stop_loss_pct=0.02,
        )
        assert result.stop_loss_triggered is True
        assert result.action_taken == "stop_loss_exit"
        assert "BTC/USDT" not in portfolio.positions
        # ~-6% equity from 3x on 2% adverse move
        assert portfolio.equity == pytest.approx(9_400.0, rel=1e-3)


@pytest.mark.unit
class TestPaperEngineLeverage:
    def test_engine_applies_config_paper_leverage_on_init(self):
        """Config paper_leverage must apply when session still has default 1x."""
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.FLAT,
            initial_equity=10_000.0,
        )
        assert session.leverage == 1.0
        engine = PaperTradingEngine(
            session,
            {"paper_leverage": 3.0, "paper_fresh_start": True, "paper_state_persistence": False},
            adaptive_enabled=False,
        )
        assert engine.session.leverage == pytest.approx(3.0)
        assert engine.portfolio.default_leverage == pytest.approx(3.0)

    def test_engine_tick_uses_session_leverage_for_pnl(self):
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.LONG,
            initial_equity=10_000.0,
            leverage=2.0,
            slippage_bps=0.0,
        )
        engine = PaperTradingEngine(
            session,
            {"paper_fresh_start": True, "paper_state_persistence": False},
            adaptive_enabled=False,
        )
        quote_enter = LivePrice(
            symbol="BTC/USDT",
            price=50_000.0,
            source=PriceSource.CRYPTOCOMPARE,
            timestamp=datetime.now(timezone.utc),
        )
        quote_hold = LivePrice(
            symbol="BTC/USDT",
            price=50_500.0,
            source=PriceSource.CRYPTOCOMPARE,
            timestamp=datetime.now(timezone.utc),
        )

        with patch(
            "tradingagents.simulator.paper_engine.fetch_live_spot_price",
            side_effect=[quote_enter, quote_hold],
        ), patch(
            "tradingagents.simulator.paper_engine.compute_strategy_signal",
            return_value="long",
        ):
            engine.tick()
            result = engine.tick()

        assert result.action_taken == "hold"
        assert engine.portfolio.equity == pytest.approx(10_200.0, rel=1e-4)
        assert engine.get_state(quote_hold).leverage == pytest.approx(2.0)

    def test_settings_leverage_applies_to_subsequent_entries(self):
        from cli.tui.settings import SettingsContext
        from cli.tui.settings.paper import PaperSettingsPlugin

        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            signal=StrategySignal.FLAT,
            initial_equity=10_000.0,
            leverage=1.0,
            slippage_bps=0.0,
        )
        config = {"paper_leverage": 1.0}
        engine = PaperTradingEngine(
            session,
            {**config, "paper_fresh_start": True, "paper_state_persistence": False},
            adaptive_enabled=False,
        )
        plugin = PaperSettingsPlugin()
        ctx = SettingsContext(config=config, extras={"engine": engine})
        msg = plugin.write(ctx, "leverage", 4.0)
        assert "4" in msg
        assert engine.session.leverage == pytest.approx(4.0)
        assert engine.portfolio.default_leverage == pytest.approx(4.0)

        quote = LivePrice(
            symbol="BTC/USDT",
            price=50_000.0,
            source=PriceSource.CRYPTOCOMPARE,
            timestamp=datetime.now(timezone.utc),
        )
        with patch(
            "tradingagents.simulator.paper_engine.fetch_live_spot_price",
            return_value=quote,
        ), patch(
            "tradingagents.simulator.paper_engine.compute_strategy_signal",
            return_value="long",
        ):
            engine.tick()

        pos = engine.portfolio.positions["BTC/USDT"]
        assert pos["leverage"] == pytest.approx(4.0)
        assert pos["size"] * pos["entry_price"] == pytest.approx(40_000.0, rel=1e-4)
