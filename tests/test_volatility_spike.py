"""Volatility spike monitor — fast-movement early review triggers."""

from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.simulator.volatility_spike import (
    VolatilitySpikeMonitor,
    build_spike_windows,
    spike_profile_for_lookback,
)


@pytest.mark.unit
class TestVolatilitySpikeMonitor:
    def test_no_trigger_on_gradual_loss(self):
        monitor = VolatilitySpikeMonitor(
            enabled=True,
            cooldown_minutes=15.0,
            windows=[(1.0, 1.5), (5.0, 2.0)],
            initial_equity=10_000.0,
        )
        start = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
        monitor.record_equity(10_000.0, start)
        monitor.record_equity(9_900.0, start + timedelta(minutes=30))
        assert monitor.check(start + timedelta(minutes=30)) is None

    def test_trigger_on_fast_one_minute_drop(self):
        monitor = VolatilitySpikeMonitor(
            enabled=True,
            cooldown_minutes=15.0,
            windows=[(1.0, 1.5)],
            initial_equity=10_000.0,
        )
        start = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
        monitor.record_equity(10_000.0, start - timedelta(seconds=30))
        monitor.record_equity(10_000.0, start)
        monitor.record_equity(9_840.0, start + timedelta(seconds=55))
        trigger = monitor.check(start + timedelta(minutes=1))
        assert trigger is not None
        assert trigger.loss_pct >= 1.5
        assert "1m" in trigger.reason or "1.0m" in trigger.reason

    def test_cooldown_blocks_repeat_trigger(self):
        monitor = VolatilitySpikeMonitor(
            enabled=True,
            cooldown_minutes=15.0,
            windows=[(1.0, 1.5)],
            initial_equity=10_000.0,
        )
        start = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
        monitor.record_equity(10_000.0, start)
        monitor.record_equity(9_800.0, start + timedelta(minutes=1))
        assert monitor.check(start + timedelta(minutes=1)) is not None
        monitor.note_review_started(start + timedelta(minutes=1))
        monitor.record_equity(9_700.0, start + timedelta(minutes=2))
        assert monitor.check(start + timedelta(minutes=2)) is None

    def test_7d_profile_skips_one_minute_window(self):
        cooldown, windows = spike_profile_for_lookback("7d")
        window_mins = [w for w, _ in windows]
        assert 1.0 not in window_mins
        assert cooldown >= 30.0

    def test_build_spike_windows_respects_config_overrides(self):
        config = {
            "paper_spike_1m_loss_pct": 2.0,
            "paper_spike_5m_loss_pct": 3.0,
            "paper_spike_10m_loss_pct": 4.0,
            "paper_spike_min_cooldown_minutes": 25.0,
        }
        cooldown, windows = build_spike_windows("8h", config)
        assert cooldown == 25.0
        by_window = dict(windows)
        assert by_window[1.0] == 2.0
        assert by_window[5.0] == 3.0
        assert by_window[10.0] == 4.0

    def test_disabled_monitor_never_triggers(self):
        monitor = VolatilitySpikeMonitor(
            enabled=False,
            windows=[(1.0, 0.5)],
        )
        start = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
        monitor.record_equity(10_000.0, start)
        monitor.record_equity(9_000.0, start + timedelta(minutes=1))
        assert monitor.check(start + timedelta(minutes=1)) is None
