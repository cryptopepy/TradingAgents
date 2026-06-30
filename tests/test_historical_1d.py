"""Tests for 1d granularity vendor mapping."""

from tradingagents.backtest.historical_data import (
    _GRANULARITY_1D,
    _VENDOR_SPECS,
    granularity_label_to_seconds,
    granularity_seconds_to_label,
)


def test_granularity_1d_in_vendor_specs():
    assert _GRANULARITY_1D in _VENDOR_SPECS
    interval, endpoint, resample = _VENDOR_SPECS[_GRANULARITY_1D]
    assert interval == "1d"
    assert endpoint == "histoday"
    assert resample is None


def test_granularity_label_round_trip():
    assert granularity_label_to_seconds("1d") == 86400
    assert granularity_seconds_to_label(86400) == "1d"
    assert granularity_seconds_to_label(3600) == "1h"
