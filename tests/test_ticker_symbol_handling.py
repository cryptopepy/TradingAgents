import unittest

import pytest

from cli.utils import normalize_ticker_symbol
from tradingagents.agents.utils.agent_utils import build_instrument_context


@pytest.mark.unit
class TickerSymbolHandlingTests(unittest.TestCase):
    def test_normalize_ticker_symbol_to_canonical_pair(self):
        self.assertEqual(normalize_ticker_symbol(" btc-usdt "), "BTC/USDT")
        self.assertEqual(normalize_ticker_symbol("ETH/USDC"), "ETH/USDC")

    def test_build_instrument_context_mentions_exact_pair(self):
        context = build_instrument_context("SOL/USD")
        self.assertIn("SOL/USD", context)
        self.assertIn("BASE/QUOTE", context)

    def test_single_get_ticker_no_shadow(self):
        import cli.main
        import cli.utils
        self.assertIs(cli.main.get_ticker, cli.utils.get_ticker)
