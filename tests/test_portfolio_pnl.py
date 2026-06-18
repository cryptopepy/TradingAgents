"""Portfolio PnL accounting tests."""

from datetime import datetime, timezone

import pytest

from tradingagents.backtest.portfolio import Direction, TransactionIntent, VirtualPortfolio


@pytest.mark.unit
def test_unrealized_pnl_uses_position_notional_not_initial_equity():
    portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
    portfolio.cash = 12_000.0
    portfolio.equity = 12_000.0
    now = datetime.now(timezone.utc)
    portfolio.apply_intent(
        TransactionIntent(
            timestamp=now,
            asset="BTC/USDT",
            direction=Direction.LONG,
            sizing_pct=1.0,
        ),
        fill_price=100.0,
    )
    portfolio.mark_to_market({"BTC/USDT": 110.0})
    # 120 units * $10 move = $1,200 unrealized on top of cash
    assert portfolio.equity == pytest.approx(13_200.0, rel=1e-6)


@pytest.mark.unit
def test_realized_pnl_matches_position_size_on_close():
    portfolio = VirtualPortfolio(initial_equity=10_000.0, fee_bps=0.0)
    now = datetime.now(timezone.utc)
    portfolio.apply_intent(
        TransactionIntent(
            timestamp=now,
            asset="BTC/USDT",
            direction=Direction.LONG,
            sizing_pct=1.0,
        ),
        fill_price=100.0,
    )
    portfolio.apply_intent(
        TransactionIntent(
            timestamp=now,
            asset="BTC/USDT",
            direction=Direction.EXIT,
        ),
        fill_price=105.0,
    )
    assert portfolio.cash == pytest.approx(10_500.0, rel=1e-6)
    assert portfolio.equity == pytest.approx(10_500.0, rel=1e-6)
