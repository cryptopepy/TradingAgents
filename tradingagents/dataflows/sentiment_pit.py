"""Point-in-time guards for live sentiment APIs."""

from __future__ import annotations

from datetime import datetime, timedelta

NO_HISTORICAL_SENTIMENT_DATA = (
    "<NO_HISTORICAL_SENTIMENT_DATA: StockTwits and Reddit APIs provide live data only; "
    "historical sentiment is unavailable for this trade_date>"
)


def is_historical_trade_date(trade_date: str) -> bool:
    """Return True when ``trade_date`` is before yesterday (not live/recent)."""
    trade = datetime.strptime(trade_date, "%Y-%m-%d").date()
    cutoff = datetime.now().date() - timedelta(days=1)
    return trade < cutoff
