"""Unified live feed router — fallback and metadata."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from tradingagents.dataflows.live_feed import LiveFeedRouter, PriceSource


@pytest.mark.unit
class TestLiveFeedRouter:
    def test_rate_limit_falls_back_to_localized_mock(self):
        router = LiveFeedRouter({})
        router._remember_anchor("BTC/USDT", 50_000.0)

        with patch(
            "tradingagents.dataflows.cryptocompare.fetch_spot_price",
            side_effect=requests.HTTPError(response=MagicMock(status_code=429)),
        ):
            quote = router.fetch_spot("BTC/USDT")

        assert quote.source == PriceSource.PLACEHOLDER
        assert quote.price > 0

    @patch("tradingagents.dataflows.crypto_common.http_get_json")
    @patch("tradingagents.dataflows.coingecko.resolve_coin_id", return_value="bitcoin")
    def test_fetch_metadata_includes_supply_and_global_cap(self, _resolve, mock_http):
        mock_http.side_effect = [
            {
                "name": "Bitcoin",
                "market_data": {
                    "circulating_supply": 19_000_000,
                    "market_cap": {"usd": 1_200_000_000_000},
                },
            },
            {"data": {"total_market_cap": {"usd": 2_500_000_000_000}}},
        ]
        meta = LiveFeedRouter({}).fetch_metadata("BTC/USDT")
        assert meta.name == "Bitcoin"
        assert meta.circulating_supply == 19_000_000
        assert meta.global_market_cap_usd == 2_500_000_000_000

    @patch("tradingagents.dataflows.live_feed.LiveFeedRouter.fetch_spot")
    @patch("tradingagents.dataflows.crypto_common.http_get_json")
    def test_intraday_ticks_fallback_on_network_error(self, mock_http, mock_spot):
        from tradingagents.dataflows.live_feed import LivePrice
        from datetime import datetime, timezone

        mock_http.side_effect = requests.ConnectionError("offline")
        mock_spot.return_value = LivePrice(
            symbol="ETH/USDT",
            price=3_000.0,
            source=PriceSource.PLACEHOLDER,
            timestamp=datetime.now(timezone.utc),
        )
        df = LiveFeedRouter({}).fetch_intraday_ticks("ETH/USDT", interval="minute", limit=5)
        assert len(df) == 1
        assert float(df["Close"].iloc[0]) == 3_000.0
