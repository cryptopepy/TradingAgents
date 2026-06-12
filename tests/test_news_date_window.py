"""News and sentiment date-window filtering."""

from datetime import datetime, timezone

import pytest

from tradingagents.dataflows.cryptocompare import get_cryptocompare_news
from tradingagents.dataflows.date_window import (
    article_date_in_range,
    lookback_start,
    timestamp_in_trade_window,
)


@pytest.mark.unit
class TestDateWindowHelpers:
    def test_lookback_start_seven_days(self):
        assert lookback_start("2026-06-11", 7) == "2026-06-04"

    def test_article_date_in_range_inclusive_end_day(self):
        published = datetime(2026, 6, 11, 23, 59, tzinfo=timezone.utc)
        assert article_date_in_range(published, "2026-06-04", "2026-06-11") is True

    def test_article_date_outside_range(self):
        published = datetime(2026, 5, 1, 12, 0)
        assert article_date_in_range(published, "2026-06-04", "2026-06-11") is False

    def test_timestamp_in_trade_window(self):
        trade_date = "2026-06-11"
        inside = datetime(2026, 6, 10, 12, 0).timestamp()
        outside = datetime(2026, 5, 1, 12, 0).timestamp()
        assert timestamp_in_trade_window(inside, trade_date, lookback_days=7) is True
        assert timestamp_in_trade_window(outside, trade_date, lookback_days=7) is False


@pytest.mark.unit
class TestCryptoCompareNewsDates:
    def test_filters_articles_by_calendar_day(self, monkeypatch):
        def fake_http(*_a, **_k):
            ts_old = int(datetime(2026, 5, 1).timestamp())
            ts_new = int(datetime(2026, 6, 10, 15, 0).timestamp())
            return {
                "Data": [
                    {"title": "Old", "published_on": ts_old, "source": "X", "body": "old"},
                    {"title": "Fresh", "published_on": ts_new, "source": "Y", "body": "new"},
                ]
            }

        monkeypatch.setattr(
            "tradingagents.dataflows.cryptocompare.http_get_json",
            fake_http,
        )
        result = get_cryptocompare_news("BTC/USDT", "2026-06-04", "2026-06-11")
        assert "Fresh" in result
        assert "Old" not in result
