"""Smart Trading mode — resolver, guards, tick eval, overlay, engine."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cli.tui.overlays.smart_trading import SmartTradingContext, SmartTradingOverlay
from tradingagents.backtest.matcher import SimulatedMatcher
from tradingagents.backtest.portfolio import Direction, TransactionIntent, VirtualPortfolio
from tradingagents.backtest.signal_filters import apply_signal_confirm_bars
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.simulator import PaperTradingEngine, PaperTradingSession, StrategySignal
from tradingagents.simulator.smart_trading.guards import (
    SmartTradingGuardState,
    check_entry_rate_limit,
    check_spike_entry_suppression,
    validate_entry,
)
from tradingagents.simulator.smart_trading.partial_tp import apply_partial_take_profit, check_partial_take_profit
from tradingagents.simulator.smart_trading.profiles import RiskMode, TradingCadence
from tradingagents.simulator.smart_trading.resolver import resolve_effective_config
from tradingagents.simulator.smart_trading.runtime import SmartTradingRuntime
from tradingagents.simulator.smart_trading.tick_eval import evaluate_smart_market_tick
from tradingagents.simulator.smart_trading.trailing_stop import update_trailing_stop
from tradingagents.simulator.smart_trading.walk_forward_validate import WalkForwardResult


def _base_config(**overrides) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(overrides)
    return cfg


@pytest.mark.unit
class TestResolver:
    @pytest.mark.parametrize(
        "cadence,risk",
        [
            (TradingCadence.SWING, RiskMode.CONSERVATIVE),
            (TradingCadence.INTRADAY, RiskMode.MODERATE),
            (TradingCadence.SCALP, RiskMode.AGGRESSIVE),
            (TradingCadence.ADAPTIVE, RiskMode.MODERATE),
        ],
    )
    def test_cadence_risk_matrix(self, cadence, risk):
        cfg = _base_config(smart_trading_enabled=True)
        eff = resolve_effective_config(
            cfg,
            leverage=3.0,
            atr_pct=0.005,
            atr_percentile=0.5,
            cadence=cadence.value,
            risk=risk.value,
        )
        assert eff.enabled is True
        assert eff.cadence == cadence.value
        assert eff.risk == risk.value
        assert eff.stop_loss_pct >= 0.0008
        assert eff.take_profit_pct == pytest.approx(eff.stop_loss_pct * 2.0, rel=1e-6)

    def test_leverage_caps_position_size(self):
        cfg = _base_config(smart_trading_enabled=True, smart_trading_cadence="scalp")
        eff = resolve_effective_config(cfg, leverage=4.0, atr_pct=0.01, cadence="scalp", risk="aggressive")
        assert eff.position_size_pct <= 0.5 / 4.0 + 1e-9

    def test_disabled_uses_paper_sl_tp(self):
        cfg = _base_config(smart_trading_enabled=False, paper_stop_loss_pct=0.03)
        eff = resolve_effective_config(cfg, leverage=1.0, atr_pct=0.01)
        assert eff.enabled is False
        assert eff.stop_loss_pct == pytest.approx(0.03)


@pytest.mark.unit
class TestGuards:
    def test_daily_trade_limit(self):
        state = SmartTradingGuardState()
        state.daily_trade_count = 20
        state.daily_reset_date = datetime.now(timezone.utc).date().isoformat()
        cfg = _base_config(smart_trading_enabled=True)
        eff = resolve_effective_config(cfg, leverage=2.0, atr_pct=0.01, cadence="scalp", risk="moderate")
        reason = check_entry_rate_limit(state, eff, datetime.now(timezone.utc))
        assert reason is not None
        assert "Max daily trades" in reason

    def test_spike_suppression_conservative(self):
        cfg = _base_config(smart_trading_enabled=True, smart_trading_risk="conservative")
        eff = resolve_effective_config(cfg, leverage=2.0, atr_pct=0.01, risk="conservative")
        reason = check_spike_entry_suppression(2.0, 1.5, eff)
        assert reason is not None

    def test_validate_entry_returns_capped_sizing(self):
        state = SmartTradingGuardState()
        portfolio = VirtualPortfolio(initial_equity=10_000.0)
        cfg = _base_config(smart_trading_enabled=True, smart_trading_cadence="scalp")
        eff = resolve_effective_config(cfg, leverage=3.0, atr_pct=0.01, cadence="scalp", risk="moderate")
        allowed, _, sizing = validate_entry(
            state, portfolio, "BTC/USDT", 50_000.0, eff, datetime.now(timezone.utc)
        )
        assert allowed is True
        assert sizing <= 0.5 / 3.0 + 1e-9


@pytest.mark.unit
class TestSignalConfirmBars:
    def test_confirm_bars_delays_entry(self):
        signals = pd.Series([1, 1, 1, 0, -1, -1])
        out = apply_signal_confirm_bars(signals, 2)
        assert list(out) == [0, 1, 1, 0, 0, -1]


@pytest.mark.unit
class TestTrailingAndPartial:
    def test_trailing_stop_ratchet(self):
        pos = {"entry_price": 100.0, "side": 1, "base_sl_pct": 0.02, "active_sl_pct": 0.02}
        sl = update_trailing_stop(pos, 100.5, activation_pct=0.003, base_sl_pct=0.02)
        assert sl <= 0.02
        assert pos.get("trailing_active") is True

    def test_partial_take_profit(self):
        pos = {"entry_price": 100.0, "side": 1, "size": 1.0}
        tp = 0.02
        assert check_partial_take_profit(pos, 101.5, tp, 0.5) is True
        portfolio = VirtualPortfolio(initial_equity=10_000.0)
        matcher = SimulatedMatcher(portfolio=portfolio)
        apply_partial_take_profit(matcher, "BTC/USDT", 101.5, pos, 0.5)
        assert pos["partial_tp_done"] is True
        assert pos["size"] == pytest.approx(0.5)


@pytest.mark.unit
class TestSmartTickEval:
    def test_entry_stamp_on_long(self):
        portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
        matcher = SimulatedMatcher(portfolio=portfolio)
        cfg = _base_config(smart_trading_enabled=True, smart_trading_cadence="scalp")
        eff = resolve_effective_config(cfg, leverage=2.0, atr_pct=0.008, cadence="scalp")
        result = evaluate_smart_market_tick(
            portfolio,
            50_000.0,
            StrategySignal.LONG,
            asset="BTC/USDT",
            matcher=matcher,
            effective=eff,
            sizing_pct=0.3,
            leverage=2.0,
        )
        assert result.action_taken == "enter_long"
        pos = portfolio.positions["BTC/USDT"]
        assert "base_sl_pct" in pos

    def test_intra_bar_stop_on_low(self):
        portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
        portfolio.apply_intent(
            TransactionIntent(
                timestamp=datetime.now(timezone.utc),
                asset="BTC/USDT",
                direction=Direction.LONG,
                sizing_pct=0.5,
                leverage=2.0,
            ),
            fill_price=50_000.0,
        )
        pos = portfolio.positions["BTC/USDT"]
        pos["base_sl_pct"] = 0.01
        pos["active_sl_pct"] = 0.01
        matcher = SimulatedMatcher(portfolio=portfolio)
        cfg = _base_config(smart_trading_enabled=True)
        eff = resolve_effective_config(cfg, leverage=2.0, atr_pct=0.01, cadence="scalp")
        result = evaluate_smart_market_tick(
            portfolio,
            49_950.0,
            StrategySignal.FLAT,
            asset="BTC/USDT",
            matcher=matcher,
            effective=eff,
            bar_high=50_000.0,
            bar_low=49_400.0,
        )
        assert result.stop_loss_triggered or result.action_taken == "stop_loss_exit"


@pytest.mark.unit
class TestSmartOverlay:
    def test_cadence_and_risk_keys(self):
        cfg = _base_config()
        overlay = SmartTradingOverlay(ctx=SmartTradingContext(config=cfg))
        overlay.open()
        assert overlay.handle_key("c") is True
        assert overlay._cadence_idx == 2
        assert overlay.handle_key("1") is True
        assert overlay._risk_idx == 0
        assert overlay.handle_key("o") is True

    def test_apply_calls_engine(self):
        cfg = _base_config()
        engine = MagicMock()
        engine.session.leverage = 3.0
        engine.apply_smart_trading.return_value = "applied"
        engine.get_state.return_value = MagicMock(
            daily_trade_count=0,
            atr_rank_pct=50.0,
            signal="flat",
            open_position=None,
            break_even_pct=None,
        )
        engine._smart.resolve.return_value = resolve_effective_config(
            _base_config(smart_trading_enabled=True),
            leverage=3.0,
            atr_pct=0.01,
            cadence="scalp",
            risk="moderate",
        )
        overlay = SmartTradingOverlay(
            ctx=SmartTradingContext(config=cfg, extras={"engine": engine}),
        )
        overlay.open()
        overlay.handle_key("\r")
        engine.apply_smart_trading.assert_called_once()


@pytest.mark.unit
class TestEngineIntegration:
    def test_refresh_signal_uses_scalp_lookback_when_enabled(self):
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            lookback="24h",
            signal=StrategySignal.FLAT,
            stop_loss_pct=0.02,
        )
        cfg = _base_config(
            smart_trading_enabled=True,
            smart_trading_cadence="scalp",
            paper_fresh_start=True,
            paper_state_persistence=False,
        )
        engine = PaperTradingEngine(session, cfg, adaptive_enabled=False)
        df = pd.DataFrame(
            {
                "Open": [100.0] * 50,
                "High": [101.0] * 50,
                "Low": [99.0] * 50,
                "Close": [100.0 + i * 0.01 for i in range(50)],
                "Volume": [1000.0] * 50,
            }
        )
        with patch(
            "tradingagents.simulator.paper_engine.fetch_historical_crypto",
            return_value=df,
        ), patch(
            "tradingagents.simulator.paper_engine.compute_strategy_signal",
            return_value="long",
        ) as mock_signal:
            engine.refresh_signal(force=True)
            assert mock_signal.called
            lb = mock_signal.call_args[0][3]
            assert getattr(lb, "value", lb) == "8h"

    def test_apply_smart_trading_rejects_bad_walk_forward(self):
        session = PaperTradingSession(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            lookback="24h",
            signal=StrategySignal.FLAT,
        )
        cfg = _base_config(smart_trading_enabled=False)
        engine = PaperTradingEngine(session, cfg, adaptive_enabled=False)
        bad = WalkForwardResult(False, 0, -5.0, "rejected")
        with patch.object(engine._smart, "validate_cadence_change", return_value=bad):
            engine.apply_smart_trading(enabled=True, cadence="scalp")
        assert cfg["smart_trading_enabled"] is False


@pytest.mark.unit
class TestMomentum:
    def test_momentum_from_closes(self):
        from tradingagents.simulator.smart_trading.momentum import momentum_signal_from_closes

        closes = pd.Series([100.0, 100.0, 100.3])
        assert momentum_signal_from_closes(closes, threshold_pct=0.15) == StrategySignal.LONG

    def test_runtime_momentum_only_when_flat(self):
        runtime = SmartTradingRuntime(_base_config(smart_trading_enabled=True))
        cfg = _base_config(smart_trading_enabled=True, smart_trading_cadence="scalp")
        eff = resolve_effective_config(cfg, leverage=3.0, atr_pct=0.01, cadence="scalp")
        df = pd.DataFrame({"Close": [100.0, 100.0, 100.5]})
        out = runtime.momentum_override(df, StrategySignal.LONG, eff, 3.0)
        assert out == StrategySignal.LONG
