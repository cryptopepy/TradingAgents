"""Point-in-time sentiment API guards."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.sentiment_pit import NO_HISTORICAL_SENTIMENT_DATA, is_historical_trade_date
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages


@pytest.mark.unit
class TestSentimentPIT:
    def test_is_historical_trade_date(self):
        old = (datetime.now().date() - timedelta(days=10)).strftime("%Y-%m-%d")
        recent = datetime.now().strftime("%Y-%m-%d")
        assert is_historical_trade_date(old) is True
        assert is_historical_trade_date(recent) is False

    def test_stocktwits_skips_historical(self):
        old = (datetime.now().date() - timedelta(days=30)).strftime("%Y-%m-%d")
        result = fetch_stocktwits_messages("SPY", trade_date=old)
        assert result == NO_HISTORICAL_SENTIMENT_DATA

    def test_reddit_skips_historical(self):
        old = (datetime.now().date() - timedelta(days=30)).strftime("%Y-%m-%d")
        result = fetch_reddit_posts("SPY", trade_date=old)
        assert result == NO_HISTORICAL_SENTIMENT_DATA

    def test_stocktwits_live_when_recent(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with patch("tradingagents.dataflows.stocktwits.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = b'{"messages": []}'
            result = fetch_stocktwits_messages("SPY", trade_date=today)
        assert "no StockTwits messages" in result
