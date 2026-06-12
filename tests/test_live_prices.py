"""Live price vendor fallback chain."""

from unittest.mock import patch

import pytest

from tradingagents.dataflows.live_prices import LivePrice, PriceSource, fetch_live_spot_price


@pytest.mark.unit
class TestLivePrices:
    @patch("tradingagents.dataflows.live_feed.LiveFeedRouter._localized_mock_ticker")
    @patch("tradingagents.dataflows.coingecko.get_simple_price", return_value=None)
    @patch("tradingagents.dataflows.cryptocompare.fetch_spot_price", return_value=43_500.0)
    def test_prefers_cryptocompare(self, _cc, _cg, _ph):
        quote = fetch_live_spot_price("BTC/USDT", {})
        assert quote.price == 43_500.0
        assert quote.source == PriceSource.CRYPTOCOMPARE

    @patch("tradingagents.dataflows.live_feed.LiveFeedRouter._localized_mock_ticker")
    @patch("tradingagents.dataflows.coingecko.get_simple_price", return_value=2_800.0)
    @patch("tradingagents.dataflows.cryptocompare.fetch_spot_price", return_value=None)
    def test_falls_back_to_coingecko(self, _cc, _cg, _ph):
        quote = fetch_live_spot_price("ETH/USDT", {})
        assert quote.source == PriceSource.COINGECKO
        assert quote.price == 2_800.0

    @patch("tradingagents.dataflows.live_feed.LiveFeedRouter._localized_mock_ticker")
    @patch("tradingagents.dataflows.coingecko.get_simple_price", return_value=None)
    @patch("tradingagents.dataflows.cryptocompare.fetch_spot_price", return_value=None)
    def test_placeholder_when_all_vendors_fail(self, _cc, _cg, mock_mock):
        from datetime import datetime, timezone

        mock_mock.return_value = LivePrice(
            symbol="SOL/USDT",
            price=99.0,
            source=PriceSource.PLACEHOLDER,
            timestamp=datetime.now(timezone.utc),
        )
        quote = fetch_live_spot_price("SOL/USDT", {})
        assert quote.source == PriceSource.PLACEHOLDER
        assert quote.price == 99.0

    @patch("tradingagents.dataflows.live_feed.LiveFeedRouter._localized_mock_ticker")
    @patch("tradingagents.dataflows.coingecko.get_simple_price", return_value=None)
    @patch("tradingagents.dataflows.cryptocompare.fetch_spot_price", return_value=None)
    @patch("tradingagents.dataflows.live_feed.LiveFeedRouter.fetch_spot")
    def test_binance_when_live_mode(self, mock_spot, _cc, _cg, _ph):
        from datetime import datetime, timezone

        mock_spot.side_effect = lambda symbol, use_binance=None: LivePrice(
            symbol=symbol,
            price=50_000.0,
            source=PriceSource.BINANCE,
            timestamp=datetime.now(timezone.utc),
        )
        quote = fetch_live_spot_price("BTC/USDT", {}, use_binance=True)
        assert quote.source == PriceSource.BINANCE
        assert isinstance(quote, LivePrice)
