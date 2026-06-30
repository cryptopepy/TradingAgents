"""Enhanced tick evaluation for Smart Trading mode."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from tradingagents.backtest.portfolio import Direction, TransactionIntent
from tradingagents.simulator.core import (
    StrategySignal,
    TickEvaluationResult,
    _position_from_portfolio,
    _resolve_take_profit_pct,
    _stop_loss_breached,
    _take_profit_hit,
    evaluate_live_market_tick,
)
from tradingagents.simulator.smart_trading.partial_tp import apply_partial_take_profit, check_partial_take_profit
from tradingagents.simulator.smart_trading.profiles import EffectiveSmartConfig
from tradingagents.simulator.smart_trading.trailing_stop import trailing_stop_breached, update_trailing_stop
from tradingagents.backtest.matcher import SimulatedMatcher
from tradingagents.backtest.portfolio import VirtualPortfolio


def _check_sl_tp_prices(
    portfolio: VirtualPortfolio,
    asset: str,
    prices: Tuple[float, ...],
    stop_loss_pct: float,
    take_profit_pct: float,
) -> Tuple[bool, bool]:
    """Check SL/TP against multiple price points (tick + bar high/low)."""
    sl_hit = False
    tp_hit = False
    for p in prices:
        if _stop_loss_breached(portfolio, asset, p, stop_loss_pct):
            sl_hit = True
        if _take_profit_hit(portfolio, asset, p, take_profit_pct):
            tp_hit = True
    return sl_hit, tp_hit


def evaluate_smart_market_tick(
    portfolio: VirtualPortfolio,
    current_tick_price: float,
    winning_strategy_signal,
    *,
    asset: str,
    matcher: SimulatedMatcher,
    effective: EffectiveSmartConfig,
    slippage_bps: float = 0.0,
    sizing_pct: Optional[float] = None,
    leverage: Optional[float] = None,
    bar_high: Optional[float] = None,
    bar_low: Optional[float] = None,
    entry_allowed: bool = True,
    block_reason: str = "",
) -> TickEvaluationResult:
    """Smart-trading tick with trailing SL, partial TP, and intra-bar checks."""
    if not effective.enabled:
        return evaluate_live_market_tick(
            portfolio,
            current_tick_price,
            winning_strategy_signal,
            asset=asset,
            matcher=matcher,
            stop_loss_pct=effective.stop_loss_pct,
            take_profit_pct=effective.take_profit_pct,
            slippage_bps=slippage_bps,
            sizing_pct=sizing_pct or effective.position_size_pct,
            leverage=leverage or effective.leverage,
        )

    signal = StrategySignal.from_value(winning_strategy_signal)
    sl_pct = effective.stop_loss_pct
    tp_pct = effective.take_profit_pct
    size = sizing_pct if sizing_pct is not None else effective.position_size_pct
    lev = leverage if leverage is not None else effective.leverage
    now = datetime.now(timezone.utc)
    price = float(current_tick_price)

    pos = portfolio.positions.get(asset)
    if pos is not None:
        pos.setdefault("base_sl_pct", sl_pct)
        pos.setdefault("active_sl_pct", sl_pct)
        sl_pct = update_trailing_stop(
            pos, price, activation_pct=effective.trailing_sl_activation_pct, base_sl_pct=sl_pct
        )

    portfolio.mark_to_market({asset: price})

    check_prices = [price]
    if effective.intra_bar_sl_tp and bar_high is not None and bar_low is not None:
        check_prices.extend([bar_high, bar_low])

    if pos is not None:
        if trailing_stop_breached(pos, price):
            matcher.submit_intent(
                TransactionIntent(timestamp=now, asset=asset, direction=Direction.EXIT),
                reference_price=price,
            )
            return _result(now, price, signal, "trailing_stop_exit", portfolio, asset, sl_pct, tp_pct, True, False)

        if check_partial_take_profit(pos, price, tp_pct, effective.partial_tp_ratio):
            apply_partial_take_profit(matcher, asset, price, pos, effective.partial_tp_ratio)
            return _result(now, price, signal, "partial_take_profit", portfolio, asset, sl_pct, tp_pct, False, True)

    sl_hit, tp_hit = _check_sl_tp_prices(portfolio, asset, tuple(check_prices), sl_pct, tp_pct)
    if sl_hit:
        matcher.submit_intent(
            TransactionIntent(timestamp=now, asset=asset, direction=Direction.EXIT),
            reference_price=price,
        )
        return _result(now, price, signal, "stop_loss_exit", portfolio, asset, sl_pct, tp_pct, True, False)
    if tp_hit:
        matcher.submit_intent(
            TransactionIntent(timestamp=now, asset=asset, direction=Direction.EXIT),
            reference_price=price,
        )
        return _result(now, price, signal, "take_profit_exit", portfolio, asset, sl_pct, tp_pct, False, True)

    # Delegate entries/exits to standard evaluator for signal logic
    if not entry_allowed and signal in (StrategySignal.LONG, StrategySignal.SHORT):
        signal = StrategySignal.FLAT

    result = evaluate_live_market_tick(
        portfolio,
        price,
        signal,
        asset=asset,
        matcher=matcher,
        stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct,
        slippage_bps=slippage_bps,
        sizing_pct=size,
        leverage=lev,
    )
    if result.action_taken in ("enter_long", "enter_short"):
        pos = portfolio.positions.get(asset)
        if pos is not None:
            pos.setdefault("base_sl_pct", sl_pct)
            pos.setdefault("active_sl_pct", sl_pct)
            pos.setdefault("entry_atr_pct", effective.atr_pct)
    if not entry_allowed and result.action_taken in ("enter_long", "enter_short"):
        result.action_taken = "hold"
    if block_reason and result.action_taken in ("enter_long", "enter_short"):
        result.action_taken = f"blocked:{block_reason[:40]}"
    return result


def _result(
    now, price, signal, action, portfolio, asset, sl_pct, tp_pct, stop, tp
) -> TickEvaluationResult:
    portfolio.mark_to_market({asset: price})
    return TickEvaluationResult(
        timestamp=now,
        price=price,
        signal=signal,
        action_taken=action,
        portfolio_equity=portfolio.equity,
        position=_position_from_portfolio(portfolio, asset, price, sl_pct, tp_pct),
        stop_loss_triggered=stop,
        take_profit_triggered=tp,
    )
