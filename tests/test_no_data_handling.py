"""Tests that empty vendor results never become fabricated data."""

import os
import unittest
from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows import crypto_candles, interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.symbol_utils import NoMarketDataError


@pytest.mark.unit
class TestLoadOhlcvNoPoison(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(os.path.dirname(__file__), "_tmp_cache")
        os.makedirs(self._tmp, exist_ok=True)
        set_config({"data_cache_dir": self._tmp})

    def tearDown(self):
        for f in os.listdir(self._tmp):
            os.remove(os.path.join(self._tmp, f))
        os.rmdir(self._tmp)

    def test_empty_download_raises_and_does_not_cache(self):
        empty = pd.DataFrame()
        with mock.patch.object(
            crypto_candles, "_fetch_ohlcv_from_vendors", side_effect=NoMarketDataError("FAKE/USDT", "FAKE/USDT", "no rows")
        ):
            with self.assertRaises(NoMarketDataError):
                crypto_candles.load_ohlcv("BTC/USDT", "2026-01-01")
        self.assertEqual(os.listdir(self._tmp), [])


@pytest.mark.unit
class TestRouteToVendorSentinel(unittest.TestCase):
    def test_no_data_from_all_vendors_returns_sentinel(self):
        def raises_no_data(symbol, *a, **k):
            raise NoMarketDataError(symbol, symbol, "no rows")

        patched = {"binance": raises_no_data, "cryptocompare": raises_no_data}
        with mock.patch.dict(
            interface.VENDOR_METHODS, {"get_crypto_ohlcv": patched}, clear=False
        ):
            result = interface.route_to_vendor(
                "get_crypto_ohlcv", "BTC/USDT", "2026-01-01", "2026-01-10"
            )
        self.assertIn("NO_DATA_AVAILABLE", result)
        self.assertIn("BTC/USDT", result)
