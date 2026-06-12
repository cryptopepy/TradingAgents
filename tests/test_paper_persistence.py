"""Paper session JSON persistence."""

import json

import pytest

from tradingagents.backtest.portfolio import VirtualPortfolio
from tradingagents.simulator.persistence import (
    load_paper_session,
    paper_session_path,
    restore_portfolio,
    save_paper_session,
)


@pytest.mark.unit
class TestPaperPersistence:
    def test_save_and_restore_roundtrip(self, tmp_path):
        config = {"data_cache_dir": str(tmp_path)}
        portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=8.0)
        portfolio.cash = 99_500.0
        portfolio.equity = 99_500.0

        path = save_paper_session(
            symbol="BTC/USDT",
            strategy_name="ema_crossover",
            lookback="24h",
            signal="long",
            portfolio=portfolio,
            parameters={"fast": 12},
            config=config,
        )
        assert path.exists()

        loaded = load_paper_session("BTC/USDT", config)
        assert loaded is not None
        assert loaded["strategy_name"] == "ema_crossover"

        restored = restore_portfolio(loaded)
        assert restored.equity == pytest.approx(99_500.0)
        assert restored.initial_equity == pytest.approx(10_000.0)

    def test_paper_session_path_is_symbol_safe(self, tmp_path):
        config = {"data_cache_dir": str(tmp_path)}
        path = paper_session_path("ETH/USDC", config)
        assert "/" not in path.name
        save_paper_session(
            symbol="ETH/USDC",
            strategy_name="rsi_mean_reversion",
            lookback="7d",
            signal="flat",
            portfolio=VirtualPortfolio(50_000.0),
            config=config,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["symbol"] == "ETH/USDC"
