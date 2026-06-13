"""Tests for paper trading price history panel."""

from datetime import datetime, timezone

import pytest

from cli.price_history import PriceHistoryLog


@pytest.mark.unit
class TestPriceHistoryLog:
    def test_records_delta_between_ticks(self):
        hist = PriceHistoryLog(max_samples=5)
        ts = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        hist.record(50_000.0, "kraken", ts)
        hist.record(50_100.0, "kraken", ts)
        latest = hist.latest
        assert latest is not None
        assert latest.delta == pytest.approx(100.0)
        assert latest.delta_pct == pytest.approx(0.2)

    def test_skips_duplicate_price_ticks(self):
        hist = PriceHistoryLog(max_samples=5)
        hist.record(64_293.90, "kraken")
        hist.record(64_293.90, "kraken")
        hist.record(64_294.00, "kraken")
        hist.record(64_294.00, "kraken")
        assert hist.sample_count == 2
        assert hist.latest is not None
        assert hist.latest.price == pytest.approx(64_294.00)

    def test_render_panel_has_samples(self):
        hist = PriceHistoryLog(max_samples=3)
        hist.record(1.0, "coingecko")
        hist.record(1.1, "kraken")
        assert hist.sample_count == 2
        assert hist.latest is not None
        assert hist.latest.price == pytest.approx(1.1)
