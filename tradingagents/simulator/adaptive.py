"""Adaptive strategy monitor — re-backtest when paper PnL stays underwater."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Deque, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveStrategyMonitor:
    """Track equity drawdown over a rolling window and trigger re-backtests."""

    loss_review_minutes: float = 60.0
    loss_threshold_pct: float = 5.0
    initial_equity: float = 10_000.0
    _peak_equity: float = field(init=False)
    _losing_since: Optional[datetime] = field(default=None, init=False)
    _samples: Deque[Tuple[datetime, float]] = field(default_factory=deque, init=False)
    _rebacktest_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._peak_equity = self.initial_equity

    @property
    def peak_equity(self) -> float:
        return self._peak_equity

    @property
    def rebacktest_count(self) -> int:
        return self._rebacktest_count

    def record_equity(self, equity: float, timestamp: Optional[datetime] = None) -> None:
        """Append an equity sample and update drawdown tracking."""
        ts = timestamp or datetime.now(timezone.utc)
        self._peak_equity = max(self._peak_equity, equity)
        self._samples.append((ts, equity))
        self._prune_old_samples(ts)

        drawdown_pct = self._drawdown_pct(equity)
        if drawdown_pct >= self.loss_threshold_pct:
            if self._losing_since is None:
                self._losing_since = ts
        else:
            self._losing_since = None

    def should_rebacktest(self, now: Optional[datetime] = None) -> bool:
        """True when drawdown exceeds threshold for ``loss_review_minutes``."""
        if self._losing_since is None:
            return False
        ts = now or datetime.now(timezone.utc)
        elapsed = (ts - self._losing_since).total_seconds()
        return elapsed >= self.loss_review_minutes * 60.0

    def mark_rebacktest_done(self) -> None:
        """Reset losing timer after a successful re-backtest cycle."""
        self._rebacktest_count += 1
        self._losing_since = None
        if self._samples:
            self._peak_equity = self._samples[-1][1]

    def current_drawdown_pct(self) -> float:
        if not self._samples:
            return 0.0
        return self._drawdown_pct(self._samples[-1][1])

    def _drawdown_pct(self, equity: float) -> float:
        if self._peak_equity <= 0:
            return 0.0
        return max(0.0, (self._peak_equity - equity) / self._peak_equity * 100.0)

    def _prune_old_samples(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=self.loss_review_minutes * 2)
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
