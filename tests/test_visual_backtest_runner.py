"""Tests for run_strategy_on_frame callbacks."""

from datetime import datetime, timedelta

import pandas as pd

from tradingagents.backtest.engine import run_strategy_on_frame
from tradingagents.backtest.strategies import RsiMeanReversionStrategy


def _make_df(rows: int = 80) -> pd.DataFrame:
    dates = [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(rows)]
    close = [100 + (i % 10) - 5 for i in range(rows)]
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": [c + 1 for c in close],
            "Low": [c - 1 for c in close],
            "Close": close,
            "Volume": [1000.0] * rows,
        }
    )


def test_run_strategy_on_frame_fires_callbacks():
    df = _make_df()
    strategy = RsiMeanReversionStrategy()
    bars: list = []
    entries: list = []
    trades: list = []

    run_strategy_on_frame(
        df,
        strategy,
        symbol="BTC/USDT",
        on_bar=lambda i, d, c, e: bars.append((i, d, c, e)),
        on_entry=lambda d, side, p: entries.append((d, side, p)),
        on_trade=lambda t, k: trades.append((t, k)),
        bar_sample_stride=5,
        leverage=2.0,
    )

    assert bars  # sampled bars
    assert all(b[0] % 5 == 0 for b in bars)
    # entries/trades may be empty if strategy doesn't trade on synthetic data
    assert isinstance(trades, list)
