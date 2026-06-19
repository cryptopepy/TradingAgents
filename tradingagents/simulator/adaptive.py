"""Adaptive strategy monitor — re-backtest when paper PnL stays underwater."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Deque, Optional, Tuple

logger = logging.getLogger(__name__)


def format_last_drawdown_review(minutes_since: Optional[float]) -> str:
    """Human-readable label for time since the last drawdown review."""
    if minutes_since is None:
        return "Never"
    if minutes_since < 1:
        return "<1m ago"
    return f"{int(minutes_since)}m ago"


@dataclass
class AdaptiveStrategyMonitor:
    """Track equity drawdown over a rolling window and trigger re-backtests."""

    loss_review_minutes: float = 60.0
    loss_threshold_pct: float = 5.0
    max_lookback_minutes: float = 0.0
    initial_equity: float = 10_000.0
    _peak_equity: float = field(init=False)
    _losing_since: Optional[datetime] = field(default=None, init=False)
    _samples: Deque[Tuple[datetime, float]] = field(default_factory=deque, init=False)
    _rebacktest_count: int = field(default=0, init=False)
    _last_drawdown_review_at: Optional[datetime] = field(default=None, init=False)
    _warned_drawdown: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._peak_equity = self.initial_equity

    @property
    def peak_equity(self) -> float:
        return self._peak_equity

    @property
    def rebacktest_count(self) -> int:
        return self._rebacktest_count

    @property
    def last_drawdown_review_at(self) -> Optional[datetime]:
        return self._last_drawdown_review_at

    def minutes_since_last_drawdown_review(
        self, now: Optional[datetime] = None
    ) -> Optional[float]:
        if self._last_drawdown_review_at is None:
            return None
        ts = now or datetime.now(timezone.utc)
        return (ts - self._last_drawdown_review_at).total_seconds() / 60.0

    def _lookback_cap_minutes(self) -> float:
        if self.max_lookback_minutes > 0:
            return self.max_lookback_minutes
        return self.loss_review_minutes

    def effective_review_window_minutes(self, now: Optional[datetime] = None) -> float:
        """Drawdown review window, never exceeding the configured lookback cap."""
        cap = self._lookback_cap_minutes()
        since = self.minutes_since_last_drawdown_review(now)
        if since is None:
            return min(self.loss_review_minutes, cap)
        return min(max(self.loss_review_minutes, since), cap)

    def note_drawdown_review(self, timestamp: Optional[datetime] = None) -> None:
        """Record that a drawdown review cycle ran at ``timestamp``."""
        self._last_drawdown_review_at = timestamp or datetime.now(timezone.utc)

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
            self._warned_drawdown = False

    def check_drawdown_warning(self, now: Optional[datetime] = None) -> Optional[str]:
        """One-shot warning when drawdown nears the sustained-review cap."""
        dd = self.current_drawdown_pct()
        if dd <= 0 or self.loss_threshold_pct <= 0:
            self._warned_drawdown = False
            return None
        ratio = dd / self.loss_threshold_pct
        if ratio < 0.5:
            self._warned_drawdown = False
            return None
        if ratio < 0.7 or self._warned_drawdown:
            return None
        self._warned_drawdown = True
        return (
            f"Drawdown watch — {dd:.2f}% "
            f"({ratio * 100:.0f}% of {self.loss_threshold_pct:.1f}% review cap)"
        )

    def should_rebacktest(self, now: Optional[datetime] = None) -> bool:
        """True when drawdown exceeds threshold for the effective review window."""
        if self._losing_since is None:
            return False
        ts = now or datetime.now(timezone.utc)
        elapsed = (ts - self._losing_since).total_seconds()
        window_minutes = self.effective_review_window_minutes(self._losing_since)
        return elapsed >= window_minutes * 60.0

    def mark_rebacktest_done(self, timestamp: Optional[datetime] = None) -> None:
        """Reset losing timer after a successful re-backtest cycle."""
        self._rebacktest_count += 1
        self._losing_since = None
        self._warned_drawdown = False
        self.note_drawdown_review(timestamp)
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
        window = self.effective_review_window_minutes(now)
        cutoff = now - timedelta(minutes=window * 2)
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
