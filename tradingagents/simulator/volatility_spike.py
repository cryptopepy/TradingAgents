"""Fast equity-movement monitor — early re-backtest before sustained drawdown triggers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional, Set, Tuple

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

# Scale spike thresholds relative to stop-loss for each watch window.
_STOP_LOSS_ANCHOR: Dict[float, float] = {
    1.0: 0.60,
    5.0: 0.85,
    10.0: 1.00,
    15.0: 1.10,
    30.0: 1.25,
}


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


@dataclass(frozen=True)
class SpikeWindowStatus:
    """Current loss vs threshold for one watch window."""

    window_minutes: float
    loss_pct: float
    threshold_pct: float

    @property
    def headroom_pct(self) -> float:
        return self.threshold_pct - self.loss_pct

    @property
    def utilization_pct(self) -> float:
        if self.threshold_pct <= 0:
            return 0.0
        return self.loss_pct / self.threshold_pct * 100.0


@dataclass(frozen=True)
class SpikeStatus:
    """Snapshot for live display and activity summaries."""

    enabled: bool
    intelligent_tuning: bool
    cooldown_minutes: float
    minutes_since_last_review: Optional[float]
    review_count: int
    windows: Tuple[SpikeWindowStatus, ...]
    tuning_note: str = ""

    @property
    def nearest(self) -> Optional[SpikeWindowStatus]:
        if not self.windows:
            return None
        return min(self.windows, key=lambda w: w.headroom_pct)

    @property
    def in_cooldown(self) -> bool:
        if self.minutes_since_last_review is None:
            return False
        return self.minutes_since_last_review < self.cooldown_minutes

    @property
    def cooldown_remaining_minutes(self) -> float:
        if not self.in_cooldown or self.minutes_since_last_review is None:
            return 0.0
        return max(0.0, self.cooldown_minutes - self.minutes_since_last_review)


def format_last_spike_review(minutes_since: Optional[float]) -> str:
    """Human-readable label for time since the last fast-move review."""
    if minutes_since is None:
        return "Never"
    if minutes_since < 1:
        return "<1m ago"
    return f"{int(minutes_since)}m ago"


def spike_profile_for_lookback(lookback: str) -> Tuple[float, List[Tuple[float, float]]]:
    """Return (cooldown_minutes, [(window_minutes, loss_threshold_pct), ...])."""
    return _DEFAULT_PROFILES.get(lookback, _FALLBACK_PROFILE)


def apply_intelligent_tuning(
    windows: List[Tuple[float, float]],
    cooldown: float,
    *,
    stop_loss_pct: float,
    noise_pct: float,
) -> Tuple[float, List[Tuple[float, float]], str]:
    """Raise thresholds in choppy conditions; anchor short windows to stop-loss."""
    sl_pct = stop_loss_pct * 100.0
    tuned: List[Tuple[float, float]] = []
    for window_min, threshold in windows:
        anchor = _STOP_LOSS_ANCHOR.get(window_min, 1.0)
        sl_floor = sl_pct * anchor
        noise_pad = noise_pct * (1.5 if window_min <= 1.0 else 1.0)
        tuned.append((window_min, round(max(threshold, sl_floor + noise_pad), 2)))

    noise_mult = 1.0 + min(0.5, noise_pct / 2.0) if noise_pct > 0 else 1.0
    tuned_cooldown = round(cooldown * noise_mult, 1)
    note = f"SL {sl_pct:.1f}%, chop {noise_pct:.2f}%"
    return tuned_cooldown, tuned, note


def build_spike_windows(
    lookback: str,
    config: dict,
    *,
    stop_loss_pct: float = 0.02,
    noise_pct: float = 0.0,
    intelligent_tuning: bool = False,
) -> Tuple[float, List[Tuple[float, float]], str]:
    """Merge lookback profile with optional config overrides and intelligent tuning."""
    cooldown, windows = spike_profile_for_lookback(lookback)
    override_cooldown = config.get("paper_spike_min_cooldown_minutes")
    if override_cooldown is not None:
        cooldown = float(override_cooldown)

    slot_defaults = {
        1.0: float(config.get("paper_spike_1m_loss_pct", 1.5)),
        5.0: float(config.get("paper_spike_5m_loss_pct", 2.0)),
        10.0: float(config.get("paper_spike_10m_loss_pct", 2.5)),
    }
    merged: List[Tuple[float, float]] = []
    for window_min, default_thr in windows:
        thr = slot_defaults.get(window_min, default_thr)
        merged.append((window_min, thr))

    tuning_note = ""
    if intelligent_tuning and config.get("paper_spike_intelligent_tuning_enabled", True):
        cooldown, merged, tuning_note = apply_intelligent_tuning(
            merged,
            cooldown,
            stop_loss_pct=stop_loss_pct,
            noise_pct=noise_pct,
        )
    return cooldown, merged, tuning_note


@dataclass
class VolatilitySpikeMonitor:
    """Detect rapid equity drops and trigger early strategy reviews."""

    enabled: bool = True
    intelligent_tuning: bool = False
    cooldown_minutes: float = 20.0
    windows: List[Tuple[float, float]] = field(default_factory=list)
    initial_equity: float = 10_000.0
    stop_loss_pct: float = 0.02
    lookback: str = "24h"
    config: dict = field(default_factory=dict)
    tuning_note: str = ""
    _samples: Deque[Tuple[datetime, float]] = field(default_factory=deque, init=False)
    _last_review_at: Optional[datetime] = field(default=None, init=False)
    _review_count: int = field(default=0, init=False)
    _warned_windows: Set[float] = field(default_factory=set, init=False)
    _last_tuning_note: str = field(default="", init=False)

    @classmethod
    def from_config(
        cls,
        config: dict,
        *,
        lookback: str,
        enabled: bool,
        initial_equity: float,
        stop_loss_pct: float = 0.02,
    ) -> VolatilitySpikeMonitor:
        intelligent = bool(config.get("paper_spike_intelligent_tuning_enabled", True))
        monitor = cls(
            enabled=enabled,
            intelligent_tuning=intelligent and enabled,
            initial_equity=initial_equity,
            stop_loss_pct=stop_loss_pct,
            lookback=lookback,
            config=dict(config),
        )
        monitor._refresh_windows()
        return monitor

    def update_lookback(self, lookback: str, config: dict) -> None:
        """Refresh window thresholds when the session lookback changes."""
        self.lookback = lookback
        self.config = dict(config)
        self._refresh_windows()

    def _refresh_windows(self) -> None:
        noise = self._recent_noise_pct()
        cooldown, windows, note = build_spike_windows(
            self.lookback,
            self.config,
            stop_loss_pct=self.stop_loss_pct,
            noise_pct=noise,
            intelligent_tuning=self.intelligent_tuning,
        )
        self.cooldown_minutes = cooldown
        self.windows = list(windows)
        self.tuning_note = note

    @property
    def review_count(self) -> int:
        return self._review_count

    def record_equity(self, equity: float, timestamp: Optional[datetime] = None) -> None:
        ts = timestamp or datetime.now(timezone.utc)
        self._samples.append((ts, equity))
        self._prune_old_samples(ts)
        if self.intelligent_tuning:
            self._maybe_retune()

    def _maybe_retune(self) -> None:
        noise = self._recent_noise_pct()
        cooldown, windows, note = build_spike_windows(
            self.lookback,
            self.config,
            stop_loss_pct=self.stop_loss_pct,
            noise_pct=noise,
            intelligent_tuning=True,
        )
        if note != self._last_tuning_note or windows != self.windows:
            self.cooldown_minutes = cooldown
            self.windows = list(windows)
            self.tuning_note = note
            self._last_tuning_note = note

    def note_review_started(self, timestamp: Optional[datetime] = None) -> None:
        """Record review at start so cooldown applies during a long optimization."""
        self._last_review_at = timestamp or datetime.now(timezone.utc)
        self._review_count += 1
        self._warned_windows.clear()

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

    def check_proximity_warning(self, now: Optional[datetime] = None) -> Optional[str]:
        """Return a one-shot warning when loss nears a spike threshold."""
        if not self.enabled or not self.windows:
            return None
        ts = now or datetime.now(timezone.utc)
        status = self.status(ts)
        if status.in_cooldown:
            return None
        for window in status.windows:
            if window.utilization_pct < 70.0:
                if window.window_minutes in self._warned_windows:
                    self._warned_windows.discard(window.window_minutes)
                continue
            if window.window_minutes in self._warned_windows:
                continue
            self._warned_windows.add(window.window_minutes)
            return (
                f"Fast-move watch — {window.loss_pct:.2f}% loss over "
                f"{window.window_minutes:g}m "
                f"({window.utilization_pct:.0f}% of {window.threshold_pct:.1f}% threshold)"
            )
        return None

    def status(self, now: Optional[datetime] = None) -> SpikeStatus:
        ts = now or datetime.now(timezone.utc)
        since: Optional[float] = None
        if self._last_review_at is not None:
            since = (ts - self._last_review_at).total_seconds() / 60.0
        window_status = tuple(
            SpikeWindowStatus(
                window_minutes=window_min,
                loss_pct=self._loss_pct_over_window(window_min, ts),
                threshold_pct=threshold,
            )
            for window_min, threshold in self.windows
        )
        return SpikeStatus(
            enabled=self.enabled,
            intelligent_tuning=self.intelligent_tuning,
            cooldown_minutes=self.cooldown_minutes,
            minutes_since_last_review=since,
            review_count=self._review_count,
            windows=window_status,
            tuning_note=self.tuning_note,
        )

    def format_status_line(self, now: Optional[datetime] = None) -> str:
        status = self.status(now)
        if not status.enabled:
            return "off"
        parts: List[str] = []
        if status.intelligent_tuning:
            parts.append("auto-tuned")
        if status.in_cooldown:
            parts.append(f"cooldown {status.cooldown_remaining_minutes:.0f}m")
        nearest = status.nearest
        if nearest is not None:
            parts.append(
                f"{nearest.loss_pct:.1f}%/{nearest.threshold_pct:.1f}% @ {nearest.window_minutes:g}m"
            )
        if status.tuning_note:
            parts.append(status.tuning_note)
        return " · ".join(parts) if parts else "watching"

    def format_status_line_compact(self, now: Optional[datetime] = None) -> str:
        """Short status for live panels (avoids blowing out column layout)."""
        status = self.status(now)
        if not status.enabled:
            return "off"
        parts: List[str] = []
        if status.in_cooldown:
            parts.append(f"cd {status.cooldown_remaining_minutes:.0f}m")
        nearest = status.nearest
        if nearest is not None:
            parts.append(
                f"{nearest.loss_pct:.1f}%/{nearest.threshold_pct:.1f}%"
                f"@{nearest.window_minutes:g}m"
            )
        elif status.intelligent_tuning:
            parts.append("auto")
        return " · ".join(parts) if parts else "ok"

    def _recent_noise_pct(self) -> float:
        if len(self._samples) < 3:
            return 0.0
        moves: List[float] = []
        for idx in range(1, len(self._samples)):
            prev_eq = self._samples[idx - 1][1]
            cur_eq = self._samples[idx][1]
            if prev_eq > 0:
                moves.append(abs((cur_eq - prev_eq) / prev_eq * 100.0))
        if not moves:
            return 0.0
        recent = sorted(moves[-30:])
        idx = max(0, min(int(len(recent) * 0.9) - 1, len(recent) - 1))
        return recent[idx]

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
