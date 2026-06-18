"""Ensure we explain winner-gate exclusions in CLI warnings."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.backtest.schemas import StrategyMetrics


def _sample_ohlcv(rows: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2026-06-01", periods=rows, freq="5min")
    close = pd.Series(range(100, 100 + rows), dtype=float)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": 1_000,
        }
    )


@pytest.mark.unit
def test_winner_gate_exclusion_adds_warning():
    from tradingagents.backtest.engine import LookbackWindow, optimize_strategies

    df = _sample_ohlcv(120)

    def fake_fetch(*_args, **_kwargs):
        return df

    def fake_eval(strategy_name: str, _df, lookback: LookbackWindow, *_args, **_kwargs):
        # RSI: higher score, but ineligible due to low trade count (2).
        if strategy_name == "rsi_mean_reversion":
            return StrategyMetrics(
                strategy_name="rsi_mean_reversion",
                lookback=lookback.value,
                net_profit_ratio=0.057,
                profit_factor=99.0,
                max_drawdown=0.0208,
                num_trades=2,
            )
        # CMO: eligible, lower score.
        return StrategyMetrics(
            strategy_name="cmo_mean_reversion",
            lookback=lookback.value,
            net_profit_ratio=0.0355,
            profit_factor=2.86,
            max_drawdown=0.0315,
            num_trades=4,
        )

    class _S:
        def __init__(self, name: str):
            self.name = name

    strategies = [_S("rsi_mean_reversion"), _S("cmo_mean_reversion")]

    config = {
        "winner_gate_enabled": True,
        "winner_min_trades": 3,
        "winner_score_mode": "composite",
        # Keep the rest minimal; enrich_optimization_config will set other defaults.
    }

    with patch("tradingagents.backtest.engine.fetch_intraday_ohlcv", side_effect=fake_fetch), patch(
        "tradingagents.backtest.engine._evaluate_strategy_on_frame",
        side_effect=fake_eval,
    ):
        result = optimize_strategies(
            "BTC/USDT",
            "2026-06-01",
            strategies=strategies,
            lookbacks=[LookbackWindow.D7],
            config=config,
        )

    assert result.winner is not None
    assert result.winner.strategy_name == "cmo_mean_reversion"
    assert any(
        "Winner gate excluded" in w
        and "rsi_mean_reversion" in w
        and "trades 2 < min 3" in w
        for w in result.warnings
    )

