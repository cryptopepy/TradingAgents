"""Partial take-profit at TP1, remainder runs to TP2."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tradingagents.backtest.matcher import SimulatedMatcher
from tradingagents.backtest.portfolio import Direction, TransactionIntent


def check_partial_take_profit(
    pos: Dict[str, Any],
    price: float,
    tp_pct: float,
    partial_ratio: float,
) -> bool:
    """True when price hit TP1 and partial not yet taken."""
    if pos.get("partial_tp_done"):
        return False
    entry = float(pos.get("entry_price", price))
    move = (price - entry) / entry
    if int(pos.get("side", 1)) < 0:
        move = -move
    tp1 = tp_pct * partial_ratio + (1 - partial_ratio) * (tp_pct * 0.5)
    return move > 0 and move >= tp1


def apply_partial_take_profit(
    matcher: SimulatedMatcher,
    asset: str,
    price: float,
    pos: Dict[str, Any],
    partial_ratio: float,
) -> bool:
    """Reduce position size by partial_ratio. Returns True if applied."""
    if pos.get("partial_tp_done"):
        return False
    size = float(pos.get("size", 0))
    if size <= 0:
        return False
    reduce = size * partial_ratio
    if reduce <= 0:
        return False
    # Simulate partial exit by shrinking size and marking
    pos["size"] = size - reduce
    pos["partial_tp_done"] = True
    pos["partial_exit_price"] = price
    matcher.portfolio.mark_to_market({asset: price})
    return True
