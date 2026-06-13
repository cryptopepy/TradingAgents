"""Live price vendor fallback chain."""

from unittest.mock import patch

import pytest
import requests

from tradingagents.dataflows.live_prices import LivePrice, PriceSource, fetch_live_spot_price


@pytest.mark.unit
class TestLivePrices:
    @patch("tradingagents.dataflows.live_feed.LiveFeedRouter._localized_mock_ticker")
    @patch("tradingagents.dataflows.coingecko.get_simple_price", return_value=None)
    @patch("tradingagents.backtest.historical_data.fetch_ccxt_spot_ticker", side_effect=Exception("offline"))
    @patch("tradingagents.dataflows.cryptocompare.fetch_spot_price", return_value=43_500.0)
    def test_prefers_cryptocompare(self, _cc, _cx, _cg, _ph):
        quote = fetch_live_spot_price("BTC/USDT", {})
        assert quote.price == 43_500.0
        assert quote.source == PriceSource.CRYPTOCOMPARE

    @patch("tradingagents.dataflows.live_feed.LiveFeedRouter._localized_mock_ticker")
    @patch("tradingagents.dataflows.coingecko.get_simple_price", return_value=2_800.0)
    @patch("tradingagents.backtest.historical_data.fetch_ccxt_spot_ticker", side_effect=Exception("offline"))
    @patch("tradingagents.dataflows.cryptocompare.fetch_spot_price", return_value=None)
    def test_falls_back_to_coingecko_when_ccxt_fails(self, _cc, _cx, _cg, _ph):
        quote = fetch_live_spot_price("ETH/USDT", {})
        assert quote.source == PriceSource.COINGECKO
        assert quote.price == 2_800.0

    @patch("tradingagents.dataflows.live_feed.LiveFeedRouter._localized_mock_ticker")
    @patch("tradingagents.dataflows.coingecko.get_simple_price", return_value=None)
    @patch(
        "tradingagents.backtest.historical_data.fetch_ccxt_spot_ticker",
        return_value=(50_100.0, "BTC/USD"),
    )
    @patch("tradingagents.dataflows.cryptocompare.fetch_spot_price", return_value=None)
    def test_prefers_ccxt_over_coingecko(self, _cc, _cx, _cg, _ph):
        quote = fetch_live_spot_price("BTC/USDT", {})
        assert quote.source == PriceSource.KRAKEN
        assert quote.price == 50_100.0
        assert quote.endpoint == "kraken BTC/USD"

    @patch("tradingagents.dataflows.live_feed.LiveFeedRouter._localized_mock_ticker")
    @patch("tradingagents.dataflows.coingecko.get_simple_price", return_value=None)
    @patch("tradingagents.backtest.historical_data.fetch_ccxt_spot_ticker", side_effect=Exception("offline"))
    @patch("tradingagents.dataflows.cryptocompare.fetch_spot_price", return_value=None)
    def test_placeholder_when_all_vendors_fail(self, _cc, _cx, _cg, mock_mock):
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
    @patch("tradingagents.backtest.historical_data.fetch_ccxt_spot_ticker", return_value=(50_000.0, "BTC/USDT"))
    @patch("tradingagents.dataflows.cryptocompare.fetch_spot_price", return_value=None)
    def test_ccxt_without_live_mode(self, _cc, _cx, _cg, _ph):
        quote = fetch_live_spot_price("BTC/USDT", {}, use_binance=True)
        assert quote.source == PriceSource.KRAKEN
        assert quote.price == 50_000.0

    def test_records_vendor_attempts_on_failure_chain(self):
        router = __import__(
            "tradingagents.dataflows.live_feed", fromlist=["LiveFeedRouter"]
        ).LiveFeedRouter({})
        with patch(
            "tradingagents.dataflows.cryptocompare.fetch_spot_price",
            side_effect=requests.HTTPError(response=__import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(status_code=429)),
        ), patch(
            "tradingagents.backtest.historical_data.fetch_ccxt_spot_ticker",
            side_effect=Exception("exchange down"),
        ), patch(
            "tradingagents.dataflows.coingecko.get_simple_price",
            return_value=42_000.0,
        ):
            quote = router.fetch_spot("BTC/USDT")
        assert quote.source == PriceSource.COINGECKO
        failures = [a for a in router.last_spot_attempts if not a.ok]
        assert any(a.vendor == "cryptocompare" for a in failures)
        assert any(a.vendor == "kraken" for a in failures)
