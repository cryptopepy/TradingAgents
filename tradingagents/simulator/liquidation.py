"""Simplified liquidation price estimates for paper trading display."""

from __future__ import annotations

from typing import Literal, Optional

Side = Literal["long", "short"]

# Rough maintenance margin buffer (0.5%) — real venues vary by tier and asset.
_DEFAULT_MAINTENANCE_MARGIN = 0.005


def estimate_liquidation_price(
    entry_price: float,
    leverage: float,
    side: Side,
    *,
    maintenance_margin: float = _DEFAULT_MAINTENANCE_MARGIN,
) -> Optional[float]:
    """Estimate the price at which margin is wiped (isolated-margin style).

  Assumes full equity backs the position at entry (``sizing_pct`` ≈ 1).
  Long liquidation is below entry; short is above.

  ``liq ≈ entry × (1 ∓ (1 − mmr) / leverage)``
    """
    if entry_price <= 0 or leverage <= 1.0:
        return None
    buffer = max(0.0, min(1.0, 1.0 - maintenance_margin)) / leverage
    if side == "long":
        return entry_price * (1.0 - buffer)
    return entry_price * (1.0 + buffer)


def leverage_display_tiers(session_leverage: float) -> list[float]:
    """Leverage multipliers to show when margin mode is on."""
    tiers = [2.0, 3.0]
    if session_leverage > 1.0 and session_leverage not in tiers:
        tiers.append(session_leverage)
    return sorted(set(tiers))


def format_liquidation_cell(
    entry_price: float,
    leverage: float,
    *,
    position_side: Optional[Side] = None,
    maintenance_margin: float = _DEFAULT_MAINTENANCE_MARGIN,
) -> str:
    """One table cell: liq price for open side, or ↓long / ↑short when flat."""
    if entry_price <= 0 or leverage <= 1.0:
        return "—"
    if position_side in ("long", "short"):
        liq = estimate_liquidation_price(
            entry_price,
            leverage,
            position_side,
            maintenance_margin=maintenance_margin,
        )
        if liq is None:
            return "—"
        return f"${liq:,.0f}"

    long_liq = estimate_liquidation_price(
        entry_price, leverage, "long", maintenance_margin=maintenance_margin
    )
    short_liq = estimate_liquidation_price(
        entry_price, leverage, "short", maintenance_margin=maintenance_margin
    )
    if long_liq is None or short_liq is None:
        return "—"
    return f"↓${long_liq:,.0f} ↑${short_liq:,.0f}"
