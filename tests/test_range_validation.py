"""Tests for backtest range validation."""

from datetime import datetime, timedelta

import pytest

from tradingagents.backtest.range_validation import (
    SAFE_MAX_BARS,
    estimate_bar_count,
    suggest_fixes,
    validate_backtest_range,
)
from tradingagents.backtest.validation import BacktestValidationError


def test_estimate_bar_count_one_hour_bars():
    start = datetime(2024, 1, 1, 0, 0)
    end = datetime(2024, 1, 1, 3, 0)
    assert estimate_bar_count(start, end, 3600) == 4


def test_validate_backtest_range_rejects_too_many_bars():
    start = datetime(2020, 1, 1)
    end = datetime(2024, 1, 1)
    with pytest.raises(BacktestValidationError) as exc:
        validate_backtest_range(start, end, 300)
    assert str(SAFE_MAX_BARS) in str(exc.value) or "too wide" in str(exc.value).lower()


def test_validate_backtest_range_rejects_short_window():
    start = datetime(2024, 6, 1, 12, 0)
    end = datetime(2024, 6, 1, 12, 30)
    with pytest.raises(BacktestValidationError):
        validate_backtest_range(start, end, 3600)


def test_suggest_fixes_includes_coarser_bar_hint():
    start = datetime(2020, 1, 1)
    end = datetime(2024, 1, 1)
    fixes = suggest_fixes(start, end, 300)
    assert any("coarser" in f.lower() or "daily" in f.lower() for f in fixes)


def test_validate_datetime_utc_parses_date_and_datetime():
    from tradingagents.backtest.validation import validate_datetime_utc

    dt = validate_datetime_utc("2024-06-15 14:30")
    assert dt.hour == 14 and dt.minute == 30
    dt2 = validate_datetime_utc("2024-06-15")
    assert dt2.hour == 0
