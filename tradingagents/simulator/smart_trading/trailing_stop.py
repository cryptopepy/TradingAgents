"""Trailing stop-loss ratchet for open positions."""

from __future__ import annotations

from typing import Any, Dict, Optional


def update_trailing_stop(
    pos: Dict[str, Any],
    price: float,
    *,
    activation_pct: float,
    base_sl_pct: float,
) -> float:
    """Ratchet stop-loss tighter after favorable move. Returns active SL %."""
    entry = float(pos.get("entry_price", price))
    if entry <= 0:
        return base_sl_pct

    side = int(pos.get("side", 1))
    move = (price - entry) / entry
    if side < 0:
        move = -move

    active_sl = float(pos.get("active_sl_pct", base_sl_pct))
    if move >= activation_pct:
        # Lock in half the favorable move as trailing floor
        trail_sl = max(base_sl_pct * 0.5, move * 0.5)
        active_sl = min(active_sl, base_sl_pct - trail_sl) if trail_sl < base_sl_pct else active_sl
        active_sl = max(0.0005, min(active_sl, base_sl_pct))
        pos["active_sl_pct"] = active_sl
        pos["trailing_active"] = True
    return float(pos.get("active_sl_pct", base_sl_pct))


def trailing_stop_breached(pos: Dict[str, Any], price: float) -> bool:
    entry = float(pos.get("entry_price", 0))
    if entry <= 0:
        return False
    sl_pct = float(pos.get("active_sl_pct", pos.get("base_sl_pct", 0.02)))
    move = (price - entry) / entry
    if int(pos.get("side", 1)) < 0:
        move = -move
    return move <= -sl_pct
