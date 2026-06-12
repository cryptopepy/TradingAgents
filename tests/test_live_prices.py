"""Live price vendor fallback chain."""

from unittest.mock import patch

import pytest

from tradingagents.dataflows.live_prices import LivePrice, PriceSource, fetch_live_spot_price


@pytest.mark.unit
class TestLivePrices:
    @patch("tradingagents.dataflows.live_prices._fetch_placeholder_spot", return_value=42_000.0)
    @patch("tradingagents.dataflows.live_prices._fetch_coingecko_spot", return_value=None)
    @patch("tradingagents.dataflows.live_prices._fetch_cryptocompare_spot", return_value=43_500.0)
    def test_prefers_cryptocompare(self, _cc, _cg, _ph):
        quote = fetch_live_spot_price("BTC/USDT", {})
        assert quote.price == 43_500.0
        assert quote.source == PriceSource.CRYPTOCOMPARE

    @patch("tradingagents.dataflows.live_prices._fetch_placeholder_spot", return_value=1.0)
    @patch("tradingagents.dataflows.live_prices._fetch_coingecko_spot", return_value=2_800.0)
    @patch("tradingagents.dataflows.live_prices._fetch_cryptocompare_spot", return_value=None)
    def test_falls_back_to_coingecko(self, _cc, _cg, _ph):
        quote = fetch_live_spot_price("ETH/USDT", {})
        assert quote.source == PriceSource.COINGECKO
        assert quote.price == 2_800.0

    @patch("tradingagents.dataflows.live_prices._fetch_placeholder_spot", return_value=99.0)
    @patch("tradingagents.dataflows.live_prices._fetch_binance_spot", return_value=None)
    @patch("tradingagents.dataflows.live_prices._fetch_coingecko_spot", return_value=None)
    @patch("tradingagents.dataflows.live_prices._fetch_cryptocompare_spot", return_value=None)
    def test_placeholder_when_all_vendors_fail(self, _cc, _cg, _bn, _ph):
        quote = fetch_live_spot_price("SOL/USDT", {})
        assert quote.source == PriceSource.PLACEHOLDER
        assert quote.price == 99.0

    @patch("tradingagents.dataflows.live_prices._fetch_placeholder_spot", return_value=1.0)
    @patch("tradingagents.dataflows.live_prices._fetch_coingecko_spot", return_value=None)
    @patch("tradingagents.dataflows.live_prices._fetch_cryptocompare_spot", return_value=None)
    @patch("tradingagents.dataflows.live_prices._fetch_binance_spot", return_value=50_000.0)
    def test_binance_when_live_mode(self, _cc, _cg, _bn, _ph):
        quote = fetch_live_spot_price("BTC/USDT", {}, use_binance=True)
        assert quote.source == PriceSource.BINANCE
        assert isinstance(quote, LivePrice)
