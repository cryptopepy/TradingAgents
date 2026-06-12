import unittest

from cli.models import AnalystType
from cli.utils import normalize_ticker_symbol
from tradingagents.graph.propagation import Propagator


class CryptoOnlyModeTests(unittest.TestCase):
    def test_normalizes_crypto_pairs(self):
        self.assertEqual(normalize_ticker_symbol("btc-usdt"), "BTC/USDT")
        self.assertEqual(normalize_ticker_symbol("ETH/USDC"), "ETH/USDC")

    def test_propagator_defaults_to_crypto(self):
        state = Propagator().create_initial_state("BTC/USDT", "2026-04-18")
        self.assertEqual(state["asset_type"], "crypto")

    def test_all_analysts_available(self):
        from cli.utils import select_analysts
        # select_analysts is interactive; verify analyst order includes fundamentals
        from cli.utils import ANALYST_ORDER
        values = [v for _, v in ANALYST_ORDER]
        self.assertIn(AnalystType.FUNDAMENTALS, values)


if __name__ == "__main__":
    unittest.main()
