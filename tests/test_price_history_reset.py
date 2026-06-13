"""Price history reset on symbol switch."""

import pytest

from cli.price_history import PriceHistoryLog


@pytest.mark.unit
def test_price_history_reset_clears_samples():
    hist = PriceHistoryLog()
    hist.record(100.0, "kraken")
    hist.record(101.0, "kraken")
    assert hist.sample_count == 2
    hist.reset()
    assert hist.sample_count == 0
    assert hist.session_high is None
