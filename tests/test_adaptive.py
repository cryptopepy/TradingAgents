"""Adaptive strategy monitor."""

from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.simulator.adaptive import AdaptiveStrategyMonitor


@pytest.mark.unit
class TestAdaptiveStrategyMonitor:
    def test_no_rebacktest_when_equity_stable(self):
        monitor = AdaptiveStrategyMonitor(
            loss_review_minutes=30,
            loss_threshold_pct=5.0,
            initial_equity=10_000.0,
        )
        now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        monitor.record_equity(10_000.0, now)
        monitor.record_equity(9_900.0, now + timedelta(minutes=10))
        assert monitor.should_rebacktest(now + timedelta(minutes=10)) is False

    def test_rebacktest_after_sustained_drawdown(self):
        monitor = AdaptiveStrategyMonitor(
            loss_review_minutes=30,
            loss_threshold_pct=5.0,
            initial_equity=10_000.0,
        )
        start = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        monitor.record_equity(10_000.0, start)
        monitor.record_equity(9_400.0, start + timedelta(minutes=5))
        assert monitor.should_rebacktest(start + timedelta(minutes=20)) is False
        assert monitor.should_rebacktest(start + timedelta(minutes=35)) is True

    def test_mark_rebacktest_resets_timer(self):
        monitor = AdaptiveStrategyMonitor(
            loss_review_minutes=10,
            loss_threshold_pct=5.0,
            initial_equity=10_000.0,
        )
        now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        monitor.record_equity(9_000.0, now)
        assert monitor.should_rebacktest(now + timedelta(minutes=15)) is True
        monitor.mark_rebacktest_done()
        assert monitor.should_rebacktest(now + timedelta(minutes=15)) is False
        assert monitor.rebacktest_count == 1
