"""Point-in-time sentiment API guards."""

from datetime import datetime, timedelta

import pytest

from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.sentiment_pit import NO_HISTORICAL_SENTIMENT_DATA, is_historical_trade_date


@pytest.mark.unit
class TestSentimentPIT:
    def test_is_historical_trade_date(self):
        old = (datetime.now().date() - timedelta(days=10)).strftime("%Y-%m-%d")
        recent = datetime.now().strftime("%Y-%m-%d")
        assert is_historical_trade_date(old) is True
        assert is_historical_trade_date(recent) is False

    def test_reddit_skips_historical(self):
        old = (datetime.now().date() - timedelta(days=30)).strftime("%Y-%m-%d")
        result = fetch_reddit_posts("BTC/USDT", trade_date=old)
        assert result == NO_HISTORICAL_SENTIMENT_DATA
