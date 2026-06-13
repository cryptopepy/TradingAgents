"""Tests for Kraken credential helpers and public REST wrappers."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestKrakenCredentials:
    def test_kraken_ccxt_config_without_keys(self):
        from tradingagents.dataflows.kraken import kraken_ccxt_config

        with patch.dict("os.environ", {}, clear=True):
            cfg = kraken_ccxt_config()
        assert cfg["enableRateLimit"] is True
        assert "apiKey" not in cfg

    def test_kraken_ccxt_config_with_keys(self):
        from tradingagents.dataflows.kraken import kraken_ccxt_config

        with patch.dict(
            "os.environ",
            {"KRAKEN_API_KEY": "key", "KRAKEN_API_SECRET": "c2VjcmV0"},
            clear=True,
        ):
            cfg = kraken_ccxt_config()
        assert cfg["apiKey"] == "key"
        assert cfg["secret"] == "c2VjcmV0"


@pytest.mark.unit
class TestKrakenPublicRest:
    @patch("tradingagents.dataflows.kraken.http_get_json")
    def test_fetch_public_ticker(self, mock_get):
        from tradingagents.dataflows.kraken import fetch_public_ticker

        mock_get.return_value = {
            "error": [],
            "result": {
                "XXBTZUSD": {
                    "c": ["65000.0", "0.1"],
                    "a": ["65001.0", "1", "65001.0"],
                    "b": ["64999.0", "1", "64999.0"],
                }
            },
        }
        result = fetch_public_ticker("XBTUSD")
        assert "XXBTZUSD" in result

    @patch("tradingagents.dataflows.kraken.http_get_json")
    def test_fetch_public_ohlc(self, mock_get):
        from tradingagents.dataflows.kraken import fetch_public_ohlc

        mock_get.return_value = {
            "error": [],
            "result": {
                "XXBTZUSD": [[1493544000, "1", "2", "0.5", "1.5", "1.2", "10", 5]],
                "last": 1493544000,
            },
        }
        rows, last_id = fetch_public_ohlc("XBTUSD", interval=5)
        assert len(rows) == 1
        assert last_id == 1493544000


@pytest.mark.unit
class TestKrakenStatus:
    @patch("tradingagents.dataflows.kraken.fetch_api_key_info")
    @patch("tradingagents.dataflows.kraken.kraken_credentials")
    def test_kraken_status_summary_new_api_format(self, mock_creds, mock_info):
        from tradingagents.dataflows.kraken import kraken_status_summary

        mock_creds.return_value = ("key", "secret")
        mock_info.return_value = {
            "apiKeyName": "paper-trading",
            "permissions": ["query-funds", "query-open-trades", "create-ws-token"],
        }
        assert kraken_status_summary() == (
            "Kraken: paper-trading (query funds, query open trades, create ws token)"
        )

    @patch("tradingagents.dataflows.kraken._private_post")
    def test_fetch_api_key_info_endpoint_name(self, mock_post):
        from tradingagents.dataflows.kraken import fetch_api_key_info

        mock_post.return_value = {"apiKeyName": "test"}
        fetch_api_key_info()
        mock_post.assert_called_once_with("GetApiKeyInfo")
