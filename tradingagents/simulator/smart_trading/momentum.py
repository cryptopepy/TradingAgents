"""Micro-momentum entry when strategy is flat."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from tradingagents.simulator.core import StrategySignal


def momentum_signal_from_closes(closes: pd.Series, threshold_pct: float = 0.15) -> Optional[StrategySignal]:
    """Return long/short if last bar move exceeds threshold %."""
    if closes is None or len(closes) < 3:
        return None
    prev = float(closes.iloc[-2])
    last = float(closes.iloc[-1])
    if prev <= 0:
        return None
    move_pct = (last - prev) / prev * 100.0
    if move_pct >= threshold_pct:
        return StrategySignal.LONG
    if move_pct <= -threshold_pct:
        return StrategySignal.SHORT
    return None
