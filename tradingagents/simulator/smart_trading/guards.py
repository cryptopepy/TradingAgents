"""Smart Trading safety guards."""

from __future__ import annotations

import math
from collections import deque
from datetime import date, datetime, timedelta, timezone
from typing import Deque, Optional

from tradingagents.backtest.portfolio import VirtualPortfolio
from tradingagents.simulator.liquidation import estimate_liquidation_price

from .profiles import EffectiveSmartConfig


class SmartTradingGuardState:
    """Mutable guard counters for a paper session."""

    def __init__(self) -> None:
        self.entry_timestamps: Deque[datetime] = deque(maxlen=500)
        self.daily_trade_count: int = 0
        self.daily_reset_date: str = ""
        self.consecutive_losses: int = 0
        self.signals_halted_until: Optional[datetime] = None
        self.halt_reason: str = ""

    def reset_daily_if_needed(self, now: datetime) -> None:
        today = now.astimezone(timezone.utc).date().isoformat()
        if self.daily_reset_date != today:
            self.daily_reset_date = today
            self.daily_trade_count = 0

    def record_entry(self, now: datetime) -> None:
        self.reset_daily_if_needed(now)
        self.daily_trade_count += 1
        self.entry_timestamps.append(now.astimezone(timezone.utc))

    def record_exit(self, now: datetime, *, was_stop_loss: bool, was_profitable: bool) -> None:
        if was_stop_loss and not was_profitable:
            self.consecutive_losses += 1
        elif was_profitable:
            self.consecutive_losses = 0

    def halt(self, now: datetime, minutes: float, reason: str) -> None:
        self.signals_halted_until = now + timedelta(minutes=minutes)
        self.halt_reason = reason

    def is_halted(self, now: datetime) -> bool:
        if self.signals_halted_until is None:
            return False
        if now >= self.signals_halted_until:
            self.signals_halted_until = None
            self.halt_reason = ""
            return False
        return True


def check_entry_rate_limit(state: SmartTradingGuardState, effective: EffectiveSmartConfig, now: datetime) -> Optional[str]:
    state.reset_daily_if_needed(now)
    if effective.max_daily_trades <= 0:
        return None
    if state.daily_trade_count >= effective.max_daily_trades:
        return f"Max daily trades ({effective.max_daily_trades}) reached"
    return None


def check_loss_streak_cooldown(
    state: SmartTradingGuardState,
    effective: EffectiveSmartConfig,
    now: datetime,
) -> Optional[str]:
    if state.consecutive_losses < effective.consecutive_loss_limit:
        return None
    if state.is_halted(now):
        return state.halt_reason or "Loss streak cooldown active"
    state.halt(now, effective.loss_cooldown_minutes, f"{state.consecutive_losses} losses — cooldown")
    return state.halt_reason


def check_liquidation_proximity(
    portfolio: VirtualPortfolio,
    asset: str,
    price: float,
    effective: EffectiveSmartConfig,
) -> Optional[str]:
    pos = portfolio.positions.get(asset)
    if not pos or effective.leverage <= 1.0:
        return None
    side = "long" if pos["side"] > 0 else "short"
    liq = estimate_liquidation_price(
        float(pos["entry_price"]),
        effective.leverage,
        side,
    )
    if liq is None or price <= 0:
        return None
    dist = abs(price - liq) / price
    if dist < effective.liquidation_guard_pct:
        return f"Liquidation proximity ({dist * 100:.1f}% to est. liq)"
    return None


def check_notional_cap(
    portfolio: VirtualPortfolio,
    asset: str,
    price: float,
    sizing_pct: float,
    leverage: float,
    effective: EffectiveSmartConfig,
) -> float:
    """Return allowed sizing_pct after notional cap."""
    equity = max(portfolio.equity, 1e-9)
    proposed_notional = equity * sizing_pct * leverage
    max_notional = equity * effective.max_notional_multiplier
    if proposed_notional <= max_notional:
        return sizing_pct
    return max(0.05, max_notional / (equity * max(lev := leverage, 1e-9)))


def check_spike_entry_suppression(
    price_change_1m_pct: float,
    spike_threshold_pct: float,
    effective: EffectiveSmartConfig,
) -> Optional[str]:
    if not effective.spike_entry_strict:
        return None
    if abs(price_change_1m_pct) >= spike_threshold_pct:
        return f"Spike entry blocked ({price_change_1m_pct:+.2f}% in 1m)"
    return None


def should_force_liquidation_exit(
    portfolio: VirtualPortfolio,
    asset: str,
    price: float,
    effective: EffectiveSmartConfig,
) -> Optional[str]:
    """Force exit when open position is too close to estimated liquidation."""
    if asset not in portfolio.positions:
        return None
    return check_liquidation_proximity(portfolio, asset, price, effective)


def validate_entry(
    state: SmartTradingGuardState,
    portfolio: VirtualPortfolio,
    asset: str,
    price: float,
    effective: EffectiveSmartConfig,
    now: datetime,
    *,
    price_change_1m_pct: float = 0.0,
    spike_threshold_pct: float = 1.5,
) -> tuple[bool, str, float]:
    """Return (allowed, reason, adjusted_sizing_pct)."""
    if not effective.enabled:
        return True, "", effective.position_size_pct

    if state.is_halted(now):
        return False, state.halt_reason or "Signals halted", effective.position_size_pct

    for check in (
        lambda: check_loss_streak_cooldown(state, effective, now),
        lambda: check_entry_rate_limit(state, effective, now),
        lambda: check_liquidation_proximity(portfolio, asset, price, effective),
        lambda: check_spike_entry_suppression(price_change_1m_pct, spike_threshold_pct, effective),
    ):
        reason = check()
        if reason:
            return False, reason, effective.position_size_pct

    sizing = min(effective.position_size_pct, 0.5 / max(effective.leverage, 1.0))
    sizing = check_notional_cap(portfolio, asset, price, sizing, effective.leverage, effective)
    return True, "", sizing
