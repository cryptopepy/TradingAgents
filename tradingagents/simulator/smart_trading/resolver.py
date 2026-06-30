"""Resolve cadence + risk + leverage into effective runtime config."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from .profiles import (
    CADENCE_PRESETS,
    EffectiveSmartConfig,
    RISK_MODIFIERS,
    RiskMode,
    TradingCadence,
    TradingCadenceProfile,
)


def _config_bool(cfg: dict, key: str, default: bool = False) -> bool:
    return bool(cfg.get(key, default))


def _config_str(cfg: dict, key: str, default: str) -> str:
    raw = cfg.get(key, default)
    return str(raw).strip().lower() if raw is not None else default


def resolve_adaptive_cadence(atr_percentile: float) -> TradingCadence:
    """Map ATR percentile rank to underlying cadence."""
    if atr_percentile < 0.20:
        return TradingCadence.SWING
    if atr_percentile < 0.60:
        return TradingCadence.INTRADAY
    return TradingCadence.SCALP


def adjust_strategy_parameters(
    strategy_name: str,
    parameters: Dict[str, Any],
    profile: TradingCadenceProfile,
) -> Dict[str, Any]:
    """Apply RSI/EMA overrides from cadence profile."""
    out = dict(parameters or {})
    if profile.rsi_oversold is not None:
        if strategy_name == "rsi_mean_reversion":
            out["oversold"] = profile.rsi_oversold
            if profile.rsi_overbought is not None:
                out["overbought"] = profile.rsi_overbought
    if profile.ema_fast is not None and strategy_name == "ema_crossover":
        out["fast_period"] = profile.ema_fast
        if profile.ema_slow is not None:
            out["slow_period"] = profile.ema_slow
    return out


def resolve_effective_config(
    config: dict,
    *,
    leverage: float,
    atr_pct: float = 0.01,
    atr_percentile: float = 0.5,
    enabled: Optional[bool] = None,
    cadence: Optional[str] = None,
    risk: Optional[str] = None,
) -> EffectiveSmartConfig:
    """Merge cadence preset, risk modifier, and leverage invariants."""
    cfg = config or {}
    is_on = _config_bool(cfg, "smart_trading_enabled", False) if enabled is None else enabled
    cadence_key = cadence or _config_str(cfg, "smart_trading_cadence", "swing")
    risk_key = risk or _config_str(cfg, "smart_trading_risk", "moderate")

    try:
        cadence_enum = TradingCadence(cadence_key)
    except ValueError:
        cadence_enum = TradingCadence.SWING
    try:
        risk_enum = RiskMode(risk_key)
    except ValueError:
        risk_enum = RiskMode.MODERATE

    adaptive_resolved: Optional[str] = None
    if cadence_enum == TradingCadence.ADAPTIVE:
        resolved = resolve_adaptive_cadence(atr_percentile)
        adaptive_resolved = resolved.value
        profile = CADENCE_PRESETS[resolved]
    else:
        profile = CADENCE_PRESETS[cadence_enum]
    risk_mod = RISK_MODIFIERS[risk_enum]

    lev = max(1.0, float(leverage or 1.0))
    atr = max(1e-6, float(atr_pct))

    sl_mult = profile.sl_atr_multiple * risk_mod.sl_atr_scale / math.sqrt(lev)
    sl_pct = max(0.0008, atr * sl_mult)
    tp_pct = sl_pct * profile.tp_reward_ratio

    size = profile.position_size_pct * risk_mod.position_size_scale
    size = min(size, 0.5 / lev)

    min_edge = profile.min_edge_fee_multiple * risk_mod.min_edge_scale
    cooldown_min = risk_mod.loss_cooldown_minutes * math.sqrt(lev)

    momentum = profile.momentum_overlay and lev >= profile.momentum_min_leverage

    if not is_on:
        sl_pct = float(cfg.get("paper_stop_loss_pct", 0.02))
        tp_raw = cfg.get("paper_take_profit_pct")
        tp_pct = float(tp_raw) if tp_raw is not None else sl_pct * 2.0
        size = float(cfg.get("position_size_pct", 1.0))
        size = min(size, 0.5 / lev) if lev > 1.0 else size

    return EffectiveSmartConfig(
        enabled=is_on,
        cadence=cadence_enum.value,
        risk=risk_enum.value,
        signal_lookback=profile.signal_lookback_override,
        horizon_weights=dict(profile.horizon_weights),
        stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct,
        position_size_pct=size,
        leverage=lev,
        min_bars_between_trades=profile.min_bars_between_trades,
        min_edge_fee_multiple=min_edge,
        regime_filter_enabled=profile.regime_filter_enabled,
        adx_trend_threshold=profile.adx_trend_threshold,
        adx_chop_threshold=profile.adx_chop_threshold,
        signal_confirm_bars=profile.signal_confirm_bars,
        max_daily_trades=profile.max_daily_trades,
        liquidation_guard_pct=risk_mod.liquidation_guard_pct,
        consecutive_loss_limit=risk_mod.consecutive_loss_limit,
        loss_cooldown_minutes=cooldown_min,
        max_notional_multiplier=risk_mod.max_notional_multiplier,
        spike_entry_strict=risk_mod.spike_entry_strict,
        momentum_overlay=momentum,
        intra_bar_sl_tp=profile.intra_bar_sl_tp,
        trailing_sl_activation_pct=float(cfg.get("smart_trading_trailing_sl_activation_pct", 0.003)),
        partial_tp_ratio=float(cfg.get("smart_trading_partial_tp_ratio", 0.5)),
        atr_pct=atr,
        strategy_param_overrides=adjust_strategy_parameters("", {}, profile),
        adaptive_resolved_cadence=adaptive_resolved,
        config_overrides={
            "min_edge_filter_enabled": min_edge > 0,
        },
    )


def format_effective_summary(effective: EffectiveSmartConfig) -> str:
    if not effective.enabled:
        return "Smart Trading off"
    cad = effective.cadence
    if effective.adaptive_resolved_cadence:
        cad = f"adaptive→{effective.adaptive_resolved_cadence}"
    return (
        f"{cad}/{effective.risk} · {effective.signal_lookback} · "
        f"SL {effective.stop_loss_pct * 100:.2f}% · TP {effective.take_profit_pct * 100:.2f}% · "
        f"size {effective.position_size_pct * 100:.0f}%"
    )
