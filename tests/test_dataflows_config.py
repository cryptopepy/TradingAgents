"""Config isolation: get/set must not leak nested-dict references."""

import copy
import unittest

import pytest

import tradingagents.default_config as default_config
from tradingagents.dataflows.config import get_config, set_config


@pytest.mark.unit
class DataflowsConfigIsolationTests(unittest.TestCase):
    def setUp(self):
        set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))

    def test_get_config_returns_deep_copy(self):
        cfg = get_config()
        cfg["data_vendors"]["core_crypto_apis"] = "cryptocompare"
        cfg["tool_vendors"]["get_crypto_ohlcv"] = "cryptocompare"

        fresh = get_config()
        self.assertEqual(fresh["data_vendors"]["core_crypto_apis"], "binance,cryptocompare")
        self.assertNotIn("get_crypto_ohlcv", fresh["tool_vendors"])

    def test_set_config_does_not_alias_caller_nested_dicts(self):
        custom = copy.deepcopy(default_config.DEFAULT_CONFIG)
        custom["data_vendors"]["core_crypto_apis"] = "cryptocompare"
        custom["tool_vendors"]["get_crypto_ohlcv"] = "cryptocompare"

        set_config(custom)

        custom["data_vendors"]["core_crypto_apis"] = "binance"
        custom["tool_vendors"]["get_crypto_ohlcv"] = "binance"

        fresh = get_config()
        self.assertEqual(fresh["data_vendors"]["core_crypto_apis"], "cryptocompare")
        self.assertEqual(fresh["tool_vendors"]["get_crypto_ohlcv"], "cryptocompare")

    def test_partial_nested_update_preserves_existing_defaults(self):
        set_config(
            {
                "data_vendors": {
                    "core_crypto_apis": "binance",
                }
            }
        )

        fresh = get_config()
        self.assertEqual(fresh["data_vendors"]["core_crypto_apis"], "binance")
        self.assertEqual(fresh["data_vendors"]["technical_indicators"], "binance")
        self.assertEqual(fresh["data_vendors"]["fundamental_data"], "coingecko")
        self.assertEqual(fresh["data_vendors"]["news_data"], "cryptocompare,lunarcrush")

    def test_nested_dict_updates_merge_one_level_deep(self):
        set_config({"tool_vendors": {"get_crypto_ohlcv": "cryptocompare"}})
        set_config({"tool_vendors": {"get_news": "cryptocompare"}})

        fresh = get_config()
        self.assertEqual(fresh["tool_vendors"]["get_crypto_ohlcv"], "cryptocompare")
        self.assertEqual(fresh["tool_vendors"]["get_news"], "cryptocompare")
