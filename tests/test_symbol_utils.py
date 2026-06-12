"""Tests for crypto pair normalization and no-data routing."""

import unittest

import pytest

from tradingagents.dataflows.symbol_utils import (
    NoMarketDataError,
    normalize_symbol,
    parse_crypto_pair,
    is_valid_crypto_pair,
    is_cache_safe,
)


@pytest.mark.unit
class TestParseCryptoPair(unittest.TestCase):
    def test_slash_format(self):
        pair = parse_crypto_pair("BTC/USDT")
        self.assertEqual(pair.base, "BTC")
        self.assertEqual(pair.quote, "USDT")
        self.assertEqual(pair.display, "BTC/USDT")
        self.assertEqual(pair.binance_symbol, "BTCUSDT")

    def test_dash_format(self):
        self.assertEqual(normalize_symbol("eth-usdc"), "ETH/USDC")

    def test_concatenated_format(self):
        self.assertEqual(normalize_symbol("BTCUSDT"), "BTC/USDT")

    def test_usd_maps_to_usdt_for_binance(self):
        pair = parse_crypto_pair("SOL/USD")
        self.assertEqual(pair.binance_symbol, "SOLUSDT")

    def test_invalid_pair_raises(self):
        with self.assertRaises(ValueError):
            parse_crypto_pair("NOTAPAIR")

    def test_is_valid_crypto_pair(self):
        self.assertTrue(is_valid_crypto_pair("BTC/USDT"))
        self.assertFalse(is_valid_crypto_pair("AAPL"))


@pytest.mark.unit
class TestNoMarketDataError(unittest.TestCase):
    def test_message_includes_resolution(self):
        err = NoMarketDataError("FOO/BAR", "FOO/BAR", "no rows")
        self.assertIn("FOO", str(err))
        self.assertEqual(err.symbol, "FOO/BAR")


@pytest.mark.unit
class TestIsCacheSafe(unittest.TestCase):
    def test_accepts_alphanumeric(self):
        self.assertTrue(is_cache_safe("BTCUSDT"))

    def test_rejects_slash(self):
        self.assertFalse(is_cache_safe("BTC/USDT"))
