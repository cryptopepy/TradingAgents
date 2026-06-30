"""Backtest datetime range validation against vendor API limits."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import List

from tradingagents.backtest.engine import _last_closed_bar_dt, _utc_now_naive
from tradingagents.backtest.validation import BacktestValidationError

# Aligned with historical_data.py vendor paging.
CCXT_MAX_BARS = 64 * 1000
CRYPTOCOMPARE_MAX_BARS = 5 * 2000
SAFE_MAX_BARS = min(CCXT_MAX_BARS, CRYPTOCOMPARE_MAX_BARS)
MIN_BARS = 30


def estimate_bar_count(
    start: datetime,
    end: datetime,
    granularity_seconds: int,
) -> int:
    """Estimate number of OHLCV bars in ``[start, end]`` inclusive."""
    if end <= start or granularity_seconds <= 0:
        return 0
    span = (end - start).total_seconds()
    return max(1, int(math.floor(span / granularity_seconds)) + 1)


def suggest_fixes(
    start: datetime,
    end: datetime,
    granularity_seconds: int,
) -> List[str]:
    """Human-readable suggestions when a range is too wide or too narrow."""
    bars = estimate_bar_count(start, end, granularity_seconds)
    suggestions: List[str] = []
    if bars > SAFE_MAX_BARS:
        max_span = timedelta(seconds=SAFE_MAX_BARS * granularity_seconds)
        suggestions.append(
            f"Narrow the window to at most ~{max_span.days} days at this bar size "
            f"(~{SAFE_MAX_BARS:,} bars max)."
        )
        if granularity_seconds < 3600:
            suggestions.append("Use a coarser bar size (e.g. 1h or 1d).")
        elif granularity_seconds < 86400:
            suggestions.append("Use daily (1d) bars for longer history.")
    if bars < MIN_BARS:
        suggestions.append(
            f"Widen the range — need at least {MIN_BARS} bars (currently ~{bars})."
        )
    if end > _utc_now_naive():
        suggestions.append("End time cannot be in the future.")
    return suggestions


def floor_end_to_closed_bar(end: datetime, granularity_seconds: int) -> datetime:
    """Cap end to the last fully closed bar (naive UTC)."""
    now = _utc_now_naive()
    capped = min(end, now)
    return _last_closed_bar_dt(capped, granularity_seconds)


def validate_backtest_range(
    start: datetime,
    end: datetime,
    granularity_seconds: int,
    *,
    now: datetime | None = None,
) -> datetime:
    """Validate range and return floored end datetime.

    Raises ``BacktestValidationError`` when invalid.
    """
    if end <= start:
        raise BacktestValidationError(
            "End datetime must be after start datetime."
        )

    now_utc = _utc_now_naive(now=now)
    if start > now_utc:
        raise BacktestValidationError(
            f"Start datetime {start:%Y-%m-%d %H:%M} cannot be in the future."
        )

    floored_end = floor_end_to_closed_bar(end, granularity_seconds)
    if floored_end <= start:
        raise BacktestValidationError(
            "Not enough history for the selected end time — try an earlier end or wait."
        )

    bars = estimate_bar_count(start, floored_end, granularity_seconds)
    if bars < MIN_BARS:
        fixes = suggest_fixes(start, floored_end, granularity_seconds)
        detail = "; ".join(fixes) if fixes else ""
        raise BacktestValidationError(
            f"Range too short (~{bars} bars, need {MIN_BARS}). {detail}".strip()
        )

    if bars > SAFE_MAX_BARS:
        fixes = suggest_fixes(start, floored_end, granularity_seconds)
        detail = " ".join(fixes)
        raise BacktestValidationError(
            f"Range too wide (~{bars:,} bars, max {SAFE_MAX_BARS:,}). {detail}".strip()
        )

    return floored_end
