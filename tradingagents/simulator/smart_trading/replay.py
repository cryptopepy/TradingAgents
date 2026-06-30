"""Replay tick history with alternate smart-trading profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from tradingagents.simulator.core import TickEvaluationResult


@dataclass
class ReplayTrade:
    timestamp: str
    action: str
    price: float
    equity: float


def replay_ticks_summary(
    ticks: List[TickEvaluationResult],
    *,
    label: str,
) -> str:
    """Summarize hypothetical actions from tick history."""
    trades = [t for t in ticks if t.action_taken not in ("hold", "feed_unavailable", "error")]
    if not trades:
        return f"Replay ({label}): no trade actions in history"
    first_eq = ticks[0].portfolio_equity if ticks else 0
    last_eq = ticks[-1].portfolio_equity if ticks else 0
    return (
        f"Replay ({label}): {len(trades)} actions, "
        f"equity ${first_eq:,.0f} → ${last_eq:,.0f}"
    )
