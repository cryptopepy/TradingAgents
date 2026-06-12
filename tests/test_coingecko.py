"""CoinGecko API client — tier routing, quote mapping, and schema parsing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from tradingagents.dataflows.coingecko import (
    CoinGeckoAPIError,
    _detect_api_tier,
    _parse_simple_price,
    _vs_currency,
    api_tier,
    fetch_coin_news,
    get_crypto_fundamentals,
    get_simple_price,
)


@pytest.mark.unit
class TestQuoteMapping:
    def test_stablecoins_map_to_usd(self):
        assert _vs_currency("USDT") == "usd"
        assert _vs_currency("USDC") == "usd"
        assert _vs_currency("BUSD") == "usd"

    def test_fiat_passthrough(self):
        assert _vs_currency("EUR") == "eur"
        assert _vs_currency("GBP") == "gbp"


@pytest.mark.unit
class TestSimplePriceParsing:
    def test_parses_valid_response(self):
        data = {"bitcoin": {"usd": 63_700.5}}
        assert _parse_simple_price(data, "bitcoin", "usd") == 63_700.5

    def test_raises_on_missing_coin(self):
        with pytest.raises(CoinGeckoAPIError, match="missing"):
            _parse_simple_price({}, "bitcoin", "usd")

    def test_raises_on_missing_quote(self):
        with pytest.raises(CoinGeckoAPIError, match="unavailable"):
            _parse_simple_price({"bitcoin": {}}, "bitcoin", "usdt")


@pytest.mark.unit
class TestApiTier:
    def setup_method(self):
        _detect_api_tier.cache_clear()

    def test_no_key_is_none(self):
        with patch.dict("os.environ", {}, clear=True):
            assert api_tier() == "none"

    def test_explicit_demo_tier(self):
        with patch.dict(
            "os.environ",
            {"COINGECKO_API_KEY": "demo-key", "COINGECKO_API_TIER": "demo"},
            clear=True,
        ):
            assert api_tier() == "demo"

    def test_auto_detects_demo_key_on_pro_host(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.content = b'{"error_code":10011,"status":{"error_message":"Demo API key"}}'
        mock_resp.json.return_value = {
            "error_code": 10011,
            "status": {"error_message": "If you are using Demo API key"},
        }
        with patch.dict("os.environ", {"COINGECKO_API_KEY": "cg-demo"}, clear=True):
            with patch("tradingagents.dataflows.coingecko.requests.get", return_value=mock_resp):
                assert _detect_api_tier("cg-demo") == "demo"


@pytest.mark.unit
class TestCoingeckoRequests:
    def setup_method(self):
        _detect_api_tier.cache_clear()

    @patch("tradingagents.dataflows.coingecko._coingecko_get")
    @patch("tradingagents.dataflows.coingecko.resolve_coin_id", return_value="bitcoin")
    def test_get_simple_price_usdt_uses_usd(self, _rid, mock_get):
        mock_get.return_value = {"bitcoin": {"usd": 63_000.0}}
        price = get_simple_price("BTC/USDT")
        assert price == 63_000.0
        mock_get.assert_called_once_with(
            "/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
        )

    @patch("tradingagents.dataflows.coingecko._coingecko_get")
    @patch("tradingagents.dataflows.coingecko.resolve_coin_id", return_value="bitcoin")
    def test_get_crypto_fundamentals_uses_usd_for_usdt(self, _rid, mock_get):
        mock_get.return_value = {
            "name": "Bitcoin",
            "categories": ["Layer 1"],
            "market_data": {
                "current_price": {"usd": 63_000},
                "market_cap": {"usd": 1_200_000_000_000},
                "fully_diluted_valuation": {"usd": 1_300_000_000_000},
                "total_volume": {"usd": 30_000_000_000},
                "circulating_supply": 19_000_000,
                "total_supply": 21_000_000,
                "max_supply": 21_000_000,
                "market_cap_rank": 1,
                "ath": {"usd": 73_000},
                "atl": {"usd": 67},
            },
            "community_data": {},
            "developer_data": {},
        }
        text = get_crypto_fundamentals("BTC/USDT", "2025-06-01")
        assert "Bitcoin" in text
        assert "63000" in text
        assert "NO_DATA_AVAILABLE" not in text

    @patch("tradingagents.dataflows.coingecko._coingecko_get")
    def test_fetch_coin_news_requires_pro(self, mock_get):
        with patch.dict(
            "os.environ",
            {"COINGECKO_API_KEY": "k", "COINGECKO_API_TIER": "demo"},
            clear=True,
        ):
            with pytest.raises(CoinGeckoAPIError, match="Pro API"):
                fetch_coin_news("bitcoin")
        mock_get.assert_not_called()

    @patch("tradingagents.dataflows.coingecko._coingecko_get")
    def test_fetch_coin_news_parses_list(self, mock_get):
        mock_get.return_value = [{"title": "BTC update", "posted_at": "2025-06-01T00:00:00Z"}]
        with patch.dict(
            "os.environ",
            {"COINGECKO_API_KEY": "k", "COINGECKO_API_TIER": "pro"},
            clear=True,
        ):
            articles = fetch_coin_news("bitcoin")
        assert articles[0]["title"] == "BTC update"

    def test_rate_limit_error_message(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.content = b""
        mock_resp.json.side_effect = ValueError()
        mock_resp.text = "rate limited"
        mock_resp.reason = "Too Many Requests"
        with patch("tradingagents.dataflows.coingecko.requests.get", return_value=mock_resp):
            with pytest.raises(CoinGeckoAPIError, match="rate limit"):
                from tradingagents.dataflows.coingecko import _coingecko_get

                _coingecko_get("/ping")

    def test_auth_failure_error_message(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.content = b'{"status":{"error_message":"Invalid API Key"}}'
        mock_resp.json.return_value = {"status": {"error_message": "Invalid API Key", "error_code": 10002}}
        with patch("tradingagents.dataflows.coingecko.requests.get", return_value=mock_resp):
            with pytest.raises(CoinGeckoAPIError, match="authentication failed"):
                from tradingagents.dataflows.coingecko import _coingecko_get

                _coingecko_get("/ping")

    def test_demo_key_on_pro_host_hint(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.content = b""
        mock_resp.json.return_value = {
            "error_code": 10011,
            "status": {"error_message": "If you are using Demo API key, change root URL"},
        }
        with patch("tradingagents.dataflows.coingecko.requests.get", return_value=mock_resp):
            with pytest.raises(CoinGeckoAPIError, match="COINGECKO_API_TIER=demo"):
                from tradingagents.dataflows.coingecko import _coingecko_get

                _coingecko_get("/ping")
