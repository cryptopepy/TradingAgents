"""Date-window helpers for point-in-time news and sentiment lookbacks."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def parse_trade_date(trade_date: str) -> date:
    """Parse ``YYYY-MM-DD`` trade / analysis date."""
    return datetime.strptime(trade_date, "%Y-%m-%d").date()


def lookback_start(trade_date: str, days: int = 7) -> str:
    """Return inclusive start date string ``days`` before ``trade_date``."""
    start = parse_trade_date(trade_date) - timedelta(days=days)
    return start.strftime("%Y-%m-%d")


def article_date_in_range(
    published: datetime,
    start_date: str,
    end_date: str,
) -> bool:
    """True when ``published`` (UTC) falls on a calendar day in [start, end]."""
    start = parse_trade_date(start_date)
    end = parse_trade_date(end_date)
    pub_day = published.astimezone(timezone.utc).date() if published.tzinfo else published.date()
    return start <= pub_day <= end


def timestamp_in_trade_window(
    epoch_seconds: float | int,
    trade_date: str,
    lookback_days: int = 7,
) -> bool:
    """True when ``epoch_seconds`` is within ``lookback_days`` ending on ``trade_date``."""
    if not epoch_seconds:
        return False
    published = datetime.utcfromtimestamp(float(epoch_seconds))
    start_date = lookback_start(trade_date, lookback_days)
    return article_date_in_range(published, start_date, trade_date)
