"""Tests for deterministic crypto instrument identity and message placeholder."""

import unittest
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    create_msg_delete,
    get_instrument_context_from_state,
    resolve_instrument_identity,
)


@pytest.mark.unit
class ResolveInstrumentIdentityTests(unittest.TestCase):
    def setUp(self):
        resolve_instrument_identity.cache_clear()

    def test_resolves_crypto_metadata_from_coingecko(self):
        with patch("tradingagents.dataflows.coingecko.get_coin_identity") as mock:
            mock.return_value = {
                "name": "Bitcoin",
                "symbol": "BTC",
                "categories": "Cryptocurrency",
                "market_cap_rank": 1,
            }
            with patch("tradingagents.dataflows.symbol_utils.parse_crypto_pair"):
                identity = resolve_instrument_identity("BTC/USDT")
        self.assertEqual(identity["name"], "Bitcoin")
        self.assertEqual(identity["symbol"], "BTC")

    def test_fails_open_on_exception(self):
        with patch(
            "tradingagents.dataflows.symbol_utils.parse_crypto_pair",
            side_effect=ValueError("bad pair"),
        ):
            self.assertEqual(resolve_instrument_identity("BAD"), {})


@pytest.mark.unit
class BuildInstrumentContextTests(unittest.TestCase):
    def test_mentions_exact_pair(self):
        context = build_instrument_context("ETH/USDC")
        self.assertIn("ETH/USDC", context)
        self.assertIn("24/7/365", context)

    def test_injects_resolved_identity(self):
        context = build_instrument_context(
            "BTC/USDT",
            "crypto",
            {"name": "Bitcoin", "symbol": "BTC", "market_cap_rank": "1"},
        )
        self.assertIn("Asset: Bitcoin", context)
        self.assertIn("Market cap rank: #1", context)


@pytest.mark.unit
class GetInstrumentContextFromStateTests(unittest.TestCase):
    def test_prefers_precomputed_context(self):
        state = {"company_of_interest": "BTC/USDT", "instrument_context": "PRECOMPUTED"}
        self.assertEqual(get_instrument_context_from_state(state), "PRECOMPUTED")

    def test_fallback_is_network_free(self):
        with patch("tradingagents.agents.utils.agent_utils.resolve_instrument_identity") as mock:
            context = get_instrument_context_from_state(
                {"company_of_interest": "ETH/USDT", "asset_type": "crypto"}
            )
        mock.assert_not_called()
        self.assertIn("ETH/USDT", context)


@pytest.mark.unit
class ContextAnchoredPlaceholderTests(unittest.TestCase):
    def _run(self, state_extra):
        state = {
            "messages": [
                HumanMessage(content="old", id="h1"),
                AIMessage(content="reply", id="a1"),
            ],
            **state_extra,
        }
        return create_msg_delete()(state)

    def test_placeholder_is_not_bare_continue(self):
        result = self._run(
            {"company_of_interest": "SOL/USDT", "asset_type": "crypto", "trade_date": "2026-05-28"}
        )
        placeholder = result["messages"][-1]
        self.assertNotEqual(placeholder.content.strip(), "Continue")
        self.assertIn("SOL/USDT", placeholder.content)
