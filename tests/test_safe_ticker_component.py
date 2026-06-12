"""safe_ticker_component rejects path-traversal and unsafe characters."""

import unittest

import pytest

from tradingagents.dataflows.utils import safe_ticker_component


@pytest.mark.unit
class TestSafeTickerComponent(unittest.TestCase):
    def test_accepts_valid_cache_keys(self):
        for ticker in ("BTCUSDT", "ETHUSDC", "SOLUSDT", "BTC-USD"):
            self.assertEqual(safe_ticker_component(ticker), ticker)

    def test_rejects_traversal(self):
        for bad in ("../etc", "..", "foo/bar"):
            with self.assertRaises(ValueError):
                safe_ticker_component(bad)

    def test_rejects_whitespace_and_null(self):
        for bad in ("BTC USDT", "BTC\x00", "BTC\n"):
            with self.assertRaises(ValueError):
                safe_ticker_component(bad)

    def test_rejects_empty(self):
        for bad in ("", None):
            with self.assertRaises(ValueError):
                safe_ticker_component(bad)

    def test_rejects_too_long(self):
        with self.assertRaises(ValueError):
            safe_ticker_component("A" * 33)

    def test_rejects_only_dots(self):
        for bad in (".", "..", "..."):
            with self.assertRaises(ValueError):
                safe_ticker_component(bad)

    def test_usable_in_path_join(self):
        import os
        ticker = safe_ticker_component("BTCUSDT")
        path = os.path.join("/tmp/cache", ticker, "data.csv")
        assert path.startswith("/tmp/cache/BTCUSDT/")
