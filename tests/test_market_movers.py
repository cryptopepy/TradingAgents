"""Tests for market movers and pair-aware paper fees."""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.market_movers import fetch_top_movers
from tradingagents.dataflows.trading_fees import paper_fee_bps, paper_transaction_cost_pct


@pytest.mark.unit
class TestTradingFees:
    def test_major_pair_uses_base_fee(self):
        cfg = {"paper_transaction_cost_pct": 0.001, "paper_alt_fee_multiplier": 2.0}
        assert paper_transaction_cost_pct("BTC/USDT", cfg) == 0.001
        assert paper_transaction_cost_pct("ETH/USD", cfg) == 0.001

    def test_alt_pair_uses_multiplier(self):
        cfg = {"paper_transaction_cost_pct": 0.001, "paper_alt_fee_multiplier": 2.5}
        assert paper_transaction_cost_pct("PEPE/USDT", cfg) == 0.0025
        assert paper_fee_bps("SOL/USDT", cfg) == 25.0


@pytest.mark.unit
class TestMarketMovers:
    def test_fetch_top_movers_uses_kraken_by_default(self):
        rows = [
            {
                "symbol": "PEPE",
                "pair": "PEPE/USD",
                "name": "PEPE",
                "change_pct": 12.5,
                "volume_usd": 50_000_000,
                "price_usd": 0.00001,
            },
            {
                "symbol": "DOGE",
                "pair": "DOGE/USD",
                "name": "DOGE",
                "change_pct": -5.2,
                "volume_usd": 200_000_000,
                "price_usd": 0.08,
            },
        ]
        with patch(
            "tradingagents.dataflows.market_movers.fetch_kraken_mover_rows",
            return_value=rows,
        ):
            snap = fetch_top_movers({"movers_provider": "kraken"}, force_refresh=True)
        assert snap.gainers[0].pair == "PEPE/USD"
        assert snap.losers[0].pair == "DOGE/USD"
        assert snap.source.startswith("kraken")
        assert snap.pair_for_hotkey(0) == "PEPE/USD"

    def test_coingecko_only_when_configured(self):
        with patch(
            "tradingagents.dataflows.market_movers.fetch_kraken_mover_rows",
            return_value=[],
        ), patch(
            "tradingagents.dataflows.market_movers._fetch_coingecko",
        ) as mock_cg:
            from tradingagents.dataflows.market_movers import MoversSnapshot
            from datetime import datetime, timezone

            mock_cg.return_value = MoversSnapshot(
                gainers=(),
                losers=(),
                fetched_at=datetime.now(timezone.utc),
                source="coingecko_markets",
            )
            with pytest.raises(RuntimeError, match="Could not load movers"):
                fetch_top_movers({"movers_provider": "auto"}, force_refresh=True)
            mock_cg.assert_called_once()

    def test_kraken_ticker_normalization(self):
        from tradingagents.dataflows.kraken import _normalize_kraken_ticker

        row = _normalize_kraken_ticker(
            "BTC/USD",
            {
                "percentage": 2.5,
                "quoteVolume": 1_000_000_000,
                "last": 65000.0,
            },
        )
        assert row is not None
        assert row["symbol"] == "BTC"
        assert row["pair"] == "BTC/USD"
        assert row["change_pct"] == 2.5
