"""Smart Trading — cadence/risk profiles and presets."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class TradingCadence(str, Enum):
    SWING = "swing"
    INTRADAY = "intraday"
    SCALP = "scalp"
    ADAPTIVE = "adaptive"


class RiskMode(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


@dataclass(frozen=True)
class TradingCadenceProfile:
    """Resolved trading style parameters for one cadence preset."""

    name: str
    signal_lookback_override: str
    horizon_weights: Dict[str, float]
    min_bars_between_trades: int
    sl_atr_multiple: float
    tp_reward_ratio: float
    position_size_pct: float
    min_edge_fee_multiple: float
    regime_filter_enabled: bool
    adx_trend_threshold: float = 25.0
    adx_chop_threshold: float = 20.0
    signal_confirm_bars: int = 0
    max_daily_trades: int = 0
    rsi_oversold: Optional[float] = None
    rsi_overbought: Optional[float] = None
    ema_fast: Optional[int] = None
    ema_slow: Optional[int] = None
    momentum_overlay: bool = False
    momentum_min_leverage: float = 2.0
    intra_bar_sl_tp: bool = False


CADENCE_PRESETS: Dict[TradingCadence, TradingCadenceProfile] = {
    TradingCadence.SWING: TradingCadenceProfile(
        name="swing",
        signal_lookback_override="24h",
        horizon_weights={"8h": 0.2, "24h": 1.0, "7d": 3.0},
        min_bars_between_trades=3,
        sl_atr_multiple=2.5,
        tp_reward_ratio=2.0,
        position_size_pct=0.80,
        min_edge_fee_multiple=5.0,
        regime_filter_enabled=True,
        adx_trend_threshold=25.0,
        adx_chop_threshold=20.0,
        signal_confirm_bars=2,
        max_daily_trades=3,
        rsi_oversold=25.0,
        rsi_overbought=75.0,
        ema_fast=10,
        ema_slow=50,
    ),
    TradingCadence.INTRADAY: TradingCadenceProfile(
        name="intraday",
        signal_lookback_override="8h",
        horizon_weights={"8h": 1.0, "24h": 1.5, "7d": 0.5},
        min_bars_between_trades=1,
        sl_atr_multiple=1.8,
        tp_reward_ratio=2.0,
        position_size_pct=0.60,
        min_edge_fee_multiple=3.0,
        regime_filter_enabled=True,
        adx_trend_threshold=22.0,
        adx_chop_threshold=18.0,
        signal_confirm_bars=1,
        max_daily_trades=8,
        rsi_oversold=35.0,
        rsi_overbought=65.0,
        ema_fast=8,
        ema_slow=21,
    ),
    TradingCadence.SCALP: TradingCadenceProfile(
        name="scalp",
        signal_lookback_override="8h",
        horizon_weights={"8h": 2.0, "24h": 0.5, "7d": 0.1},
        min_bars_between_trades=0,
        sl_atr_multiple=1.2,
        tp_reward_ratio=2.0,
        position_size_pct=0.40,
        min_edge_fee_multiple=1.5,
        regime_filter_enabled=False,
        signal_confirm_bars=0,
        max_daily_trades=20,
        rsi_oversold=40.0,
        rsi_overbought=60.0,
        ema_fast=5,
        ema_slow=15,
        momentum_overlay=True,
        momentum_min_leverage=2.0,
        intra_bar_sl_tp=True,
    ),
    TradingCadence.ADAPTIVE: TradingCadenceProfile(
        name="adaptive",
        signal_lookback_override="8h",
        horizon_weights={"8h": 1.0, "24h": 1.0, "7d": 0.5},
        min_bars_between_trades=1,
        sl_atr_multiple=1.5,
        tp_reward_ratio=2.0,
        position_size_pct=0.50,
        min_edge_fee_multiple=2.5,
        regime_filter_enabled=True,
        adx_trend_threshold=22.0,
        adx_chop_threshold=18.0,
        signal_confirm_bars=0,
        max_daily_trades=12,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        momentum_overlay=True,
        momentum_min_leverage=1.0,
    ),
}


@dataclass(frozen=True)
class RiskModifier:
    """Multipliers applied on top of cadence preset."""

    name: str
    sl_atr_scale: float
    position_size_scale: float
    min_edge_scale: float
    liquidation_guard_pct: float
    consecutive_loss_limit: int
    loss_cooldown_minutes: float
    max_notional_multiplier: float
    spike_entry_strict: bool


RISK_MODIFIERS: Dict[RiskMode, RiskModifier] = {
    RiskMode.CONSERVATIVE: RiskModifier(
        name="conservative",
        sl_atr_scale=1.25,
        position_size_scale=0.70,
        min_edge_scale=1.3,
        liquidation_guard_pct=0.30,
        consecutive_loss_limit=2,
        loss_cooldown_minutes=45.0,
        max_notional_multiplier=2.0,
        spike_entry_strict=True,
    ),
    RiskMode.MODERATE: RiskModifier(
        name="moderate",
        sl_atr_scale=1.0,
        position_size_scale=1.0,
        min_edge_scale=1.0,
        liquidation_guard_pct=0.20,
        consecutive_loss_limit=3,
        loss_cooldown_minutes=30.0,
        max_notional_multiplier=3.0,
        spike_entry_strict=False,
    ),
    RiskMode.AGGRESSIVE: RiskModifier(
        name="aggressive",
        sl_atr_scale=0.75,
        position_size_scale=1.15,
        min_edge_scale=0.7,
        liquidation_guard_pct=0.15,
        consecutive_loss_limit=4,
        loss_cooldown_minutes=20.0,
        max_notional_multiplier=4.0,
        spike_entry_strict=True,
    ),
}


@dataclass
class EffectiveSmartConfig:
    """Runtime config merged from cadence + risk + leverage + ATR."""

    enabled: bool
    cadence: str
    risk: str
    signal_lookback: str
    horizon_weights: Dict[str, float]
    stop_loss_pct: float
    take_profit_pct: float
    position_size_pct: float
    leverage: float
    min_bars_between_trades: int
    min_edge_fee_multiple: float
    regime_filter_enabled: bool
    adx_trend_threshold: float
    adx_chop_threshold: float
    signal_confirm_bars: int
    max_daily_trades: int
    liquidation_guard_pct: float
    consecutive_loss_limit: int
    loss_cooldown_minutes: float
    max_notional_multiplier: float
    spike_entry_strict: bool
    momentum_overlay: bool
    intra_bar_sl_tp: bool
    trailing_sl_activation_pct: float
    partial_tp_ratio: float
    atr_pct: float = 0.0
    strategy_param_overrides: Dict[str, Any] = field(default_factory=dict)
    config_overrides: Dict[str, Any] = field(default_factory=dict)
    adaptive_resolved_cadence: Optional[str] = None

    def to_filter_config(self, base: dict) -> dict:
        """Merge into config dict for prepare_strategy_signals."""
        merged = dict(base)
        merged.update(self.config_overrides)
        merged["regime_filter_enabled"] = self.regime_filter_enabled
        merged["adx_trend_threshold"] = self.adx_trend_threshold
        merged["adx_chop_threshold"] = self.adx_chop_threshold
        merged["min_bars_between_trades"] = self.min_bars_between_trades
        merged["min_edge_fee_multiple"] = self.min_edge_fee_multiple
        merged["min_edge_filter_enabled"] = self.min_edge_fee_multiple > 0
        merged["signal_confirm_bars"] = self.signal_confirm_bars
        merged["position_size_pct"] = self.position_size_pct
        merged["winner_horizon_weights"] = self.horizon_weights
        if self.cadence == "scalp":
            merged["winner_require_long_horizon"] = False
        return merged
