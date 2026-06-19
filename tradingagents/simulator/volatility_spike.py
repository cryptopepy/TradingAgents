"""Fast equity-movement monitor — early re-backtest before sustained drawdown triggers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional, Tuple

# (cooldown minutes, window specs as (minutes, loss %))
_DEFAULT_PROFILES: Dict[str, Tuple[float, List[Tuple[float, float]]]] = {
    # 5m-bar strategies — react to short bursts
    "8h": (15.0, [(1.0, 1.5), (5.0, 2.0), (10.0, 2.5)]),
    # 15m-bar strategies — still watch 1m but slightly looser on longer windows
    "24h": (20.0, [(1.0, 1.5), (5.0, 2.0), (10.0, 3.0)]),
    # 1h-bar strategies — ignore 1m noise, use wider windows
    "7d": (45.0, [(5.0, 2.0), (15.0, 3.0), (30.0, 4.0)]),
}

_FALLBACK_PROFILE = _DEFAULT_PROFILES["24h"]


@dataclass(frozen=True)
class SpikeTrigger:
    """A detected fast equity drop that warrants an early review."""

    loss_pct: float
    window_minutes: float
    threshold_pct: float

    @property
    def reason(self) -> str:
        return (
            f"{self.loss_pct:.2f}% loss over {self.window_minutes:g}m "
            f"(threshold {self.threshold_pct:.1f}%)"
        )


def spike_profile_for_lookback(lookback: str) -> Tuple[float, List[Tuple[float, float]]]:
    """Return (cooldown_minutes, [(window_minutes, loss_threshold_pct), ...])."""
    return _DEFAULT_PROFILES.get(lookback, _FALLBACK_PROFILE)


def build_spike_windows(
    lookback: str,
    config: dict,
) -> Tuple[float, List[Tuple[float, float]]]:
    """Merge lookback profile with optional config threshold overrides."""
    cooldown, windows = spike_profile_for_lookback(lookback)
    override_cooldown = config.get("paper_spike_min_cooldown_minutes")
    if override_cooldown is not None:
        cooldown = float(override_cooldown)

    # Config keys apply to the short/medium/long slots used by 8h/24h profiles.
    slot_defaults = {
        1.0: float(config.get("paper_spike_1m_loss_pct", 1.5)),
        5.0: float(config.get("paper_spike_5m_loss_pct", 2.0)),
        10.0: float(config.get("paper_spike_10m_loss_pct", 2.5)),
    }
    merged: List[Tuple[float, float]] = []
    for window_min, default_thr in windows:
        thr = slot_defaults.get(window_min, default_thr)
        merged.append((window_min, thr))
    return cooldown, merged


@dataclass
class VolatilitySpikeMonitor:
    """Detect rapid equity drops and trigger early strategy reviews."""

    enabled: bool = True
    cooldown_minutes: float = 20.0
    windows: List[Tuple[float, float]] = field(default_factory=list)
    initial_equity: float = 10_000.0
    _samples: Deque[Tuple[datetime, float]] = field(default_factory=deque, init=False)
    _last_review_at: Optional[datetime] = field(default=None, init=False)
    _review_count: int = field(default=0, init=False)

    @classmethod
    def from_config(
        cls,
        config: dict,
        *,
        lookback: str,
        enabled: bool,
        initial_equity: float,
    ) -> VolatilitySpikeMonitor:
        cooldown, windows = build_spike_windows(lookback, config)
        return cls(
            enabled=enabled,
            cooldown_minutes=cooldown,
            windows=list(windows),
            initial_equity=initial_equity,
        )

    def update_lookback(self, lookback: str, config: dict) -> None:
        """Refresh window thresholds when the session lookback changes."""
        cooldown, windows = build_spike_windows(lookback, config)
        self.cooldown_minutes = cooldown
        self.windows = list(windows)

    @property
    def review_count(self) -> int:
        return self._review_count

    def record_equity(self, equity: float, timestamp: Optional[datetime] = None) -> None:
        ts = timestamp or datetime.now(timezone.utc)
        self._samples.append((ts, equity))
        self._prune_old_samples(ts)

    def note_review_started(self, timestamp: Optional[datetime] = None) -> None:
        """Record review at start so cooldown applies during a long optimization."""
        self._last_review_at = timestamp or datetime.now(timezone.utc)
        self._review_count += 1

    def check(self, now: Optional[datetime] = None) -> Optional[SpikeTrigger]:
        """Return a trigger when a configured window breach is detected."""
        if not self.enabled or not self.windows:
            return None
        ts = now or datetime.now(timezone.utc)
        if self._last_review_at is not None:
            elapsed = (ts - self._last_review_at).total_seconds() / 60.0
            if elapsed < self.cooldown_minutes:
                return None
        for window_min, threshold in self.windows:
            loss = self._loss_pct_over_window(window_min, ts)
            if loss >= threshold:
                return SpikeTrigger(
                    loss_pct=loss,
                    window_minutes=window_min,
                    threshold_pct=threshold,
                )
        return None

    def _loss_pct_over_window(self, minutes: float, now: datetime) -> float:
        if len(self._samples) < 2:
            return 0.0
        cutoff = now - timedelta(minutes=minutes)
        if self._samples[0][0] > cutoff:
            return 0.0
        baseline = self._equity_at_or_before(cutoff)
        if baseline is None:
            return 0.0
        _, baseline_eq = baseline
        current_eq = self._samples[-1][1]
        if baseline_eq <= 0:
            return 0.0
        return max(0.0, (baseline_eq - current_eq) / baseline_eq * 100.0)

    def _equity_at_or_before(
        self, cutoff: datetime
    ) -> Optional[Tuple[datetime, float]]:
        best: Optional[Tuple[datetime, float]] = None
        for ts, eq in self._samples:
            if ts <= cutoff:
                best = (ts, eq)
            else:
                break
        return best

    def _prune_old_samples(self, now: datetime) -> None:
        max_window = max((w for w, _ in self.windows), default=30.0)
        cutoff = now - timedelta(minutes=max_window * 2)
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
