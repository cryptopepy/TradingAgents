"""Kraken ticker normalization and mover row tests."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestKrakenMoverRows:
    def test_normalize_rest_ticker(self):
        from tradingagents.dataflows.kraken import _normalize_rest_ticker

        row = _normalize_rest_ticker(
            "XXBTZUSD",
            {
                "c": ["65000.0", "0.1"],
                "o": "64000.0",
                "v": ["100", "5000"],
            },
        )
        assert row is not None
        assert row["pair"] == "BTC/USD"
        assert row["change_pct"] == pytest.approx(1.5625, rel=1e-3)

    def test_fetch_kraken_mover_rows_filters_volume(self):
        from tradingagents.dataflows.kraken import fetch_kraken_mover_rows

        fake_tickers = {
            "SOL/USD": {
                "percentage": 8.0,
                "quoteVolume": 5_000_000,
                "last": 150.0,
            },
            "LOW/USD": {
                "percentage": 50.0,
                "quoteVolume": 1000.0,
                "last": 1.0,
            },
        }

        mock_exchange = MagicMock()
        mock_exchange.load_markets.return_value = None
        mock_exchange.fetch_tickers.return_value = fake_tickers

        with patch("tradingagents.dataflows.kraken.create_ccxt_kraken", return_value=mock_exchange):
            rows = fetch_kraken_mover_rows(min_volume_usd=1_000_000)
        assert len(rows) == 1
        assert rows[0]["pair"] == "SOL/USD"
