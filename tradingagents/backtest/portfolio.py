"""Virtual portfolio and signal-to-intent conversion for paper trading."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, Field


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    EXIT = "EXIT"


class TransactionIntent(BaseModel):
    """Broker-agnostic order intent produced from strategy signals."""

    timestamp: datetime
    asset: str
    direction: Direction
    leverage: float = 1.0
    sizing_pct: float = 1.0


class PositionSnapshot(BaseModel):
    asset: str
    side: str
    size: float
    entry_price: float
    leverage: float
    unrealized_pnl: float = 0.0


class PortfolioSnapshot(BaseModel):
    timestamp: datetime
    equity: float
    cash: float
    positions: List[PositionSnapshot] = Field(default_factory=list)
    margin_used: float = 0.0
    margin_available: float = 0.0


class VirtualPortfolio:
    """In-memory portfolio for backtest and paper-trading simulation.

    Paper trading defaults to ``$10,000`` cash with configurable fees and
    long/short margin via per-intent ``leverage`` and ``sizing_pct``.
    """

    def __init__(
        self,
        initial_equity: float = 1.0,
        *,
        fee_bps: float = 10.0,
        default_leverage: float = 1.0,
    ) -> None:
        self.initial_equity = initial_equity
        self.cash = initial_equity
        self.equity = initial_equity
        self.fee_bps = fee_bps
        self.default_leverage = default_leverage
        self.positions: Dict[str, Dict[str, Any]] = {}
        self._last_prices: Dict[str, float] = {}
        self._history: List[PortfolioSnapshot] = []
        self.total_fees_paid: float = 0.0

    @property
    def margin_used(self) -> float:
        used = 0.0
        for pos in self.positions.values():
            notional = pos["size"] * pos["entry_price"]
            used += notional / max(pos.get("leverage", 1.0), 1e-9)
        return used

    @property
    def margin_available(self) -> float:
        return max(self.equity - self.margin_used, 0.0)

    def _charge_fee(self, notional: float) -> None:
        fee = notional * (self.fee_bps / 10_000.0)
        self.cash -= fee
        self.total_fees_paid += fee

    def apply_intent(self, intent: TransactionIntent, fill_price: float) -> None:
        """Apply a filled intent at ``fill_price``."""
        asset = intent.asset
        self._last_prices[asset] = fill_price

        if intent.direction == Direction.EXIT:
            pos = self.positions.get(asset)
            if pos:
                self._charge_fee(pos["size"] * fill_price)
            self._close_position(asset, fill_price)
            return

        side = 1 if intent.direction == Direction.LONG else -1
        if asset in self.positions:
            existing = self.positions[asset]
            if existing["side"] != side:
                self._close_position(asset, fill_price)

        deploy = self.equity * intent.sizing_pct
        leverage = intent.leverage or self.default_leverage
        notional = deploy * leverage
        size = notional / fill_price if fill_price > 0 else 0.0
        self._charge_fee(notional)

        self.positions[asset] = {
            "side": side,
            "size": size,
            "entry_price": fill_price,
            "leverage": leverage,
            "sizing_pct": intent.sizing_pct,
        }
        self._recompute_equity()

    def _position_notional(self, pos: Dict[str, Any]) -> float:
        return pos["size"] * pos["entry_price"]

    def _position_pnl(self, pos: Dict[str, Any], price: float) -> float:
        move = (price - pos["entry_price"]) / pos["entry_price"]
        if pos["side"] < 0:
            move = -move
        # Notional at entry already includes leverage (deploy × leverage).
        return self._position_notional(pos) * move

    def _close_position(self, asset: str, price: float) -> None:
        pos = self.positions.pop(asset, None)
        if not pos:
            return
        pnl = self._position_pnl(pos, price)
        self.cash += pnl
        self.equity = self.cash
        self._recompute_equity()

    def mark_to_market(self, prices: Dict[str, float]) -> None:
        """Update equity from latest marks without closing positions."""
        self._last_prices.update(prices)
        self._recompute_equity()

    def _recompute_equity(self) -> None:
        unrealized = 0.0
        for asset, pos in self.positions.items():
            mark = self._last_prices.get(asset, pos["entry_price"])
            unrealized += self._position_pnl(pos, mark)
        self.equity = self.cash + unrealized

    def snapshot(self, timestamp: Optional[datetime] = None) -> PortfolioSnapshot:
        """Return a point-in-time portfolio state."""
        ts = timestamp or datetime.utcnow()
        positions: List[PositionSnapshot] = []
        for asset, pos in self.positions.items():
            mark = self._last_prices.get(asset, pos["entry_price"])
            upnl = self._position_pnl(pos, mark)
            positions.append(
                PositionSnapshot(
                    asset=asset,
                    side="long" if pos["side"] > 0 else "short",
                    size=pos["size"],
                    entry_price=pos["entry_price"],
                    leverage=pos.get("leverage", 1.0),
                    unrealized_pnl=upnl,
                )
            )
        snap = PortfolioSnapshot(
            timestamp=ts,
            equity=self.equity,
            cash=self.cash,
            positions=positions,
            margin_used=self.margin_used,
            margin_available=self.margin_available,
        )
        self._history.append(snap)
        return snap


def signals_to_intents(
    df: pd.DataFrame,
    symbol: str,
    signals: pd.Series,
    *,
    leverage: float = 1.0,
    sizing_pct: float = 1.0,
) -> List[TransactionIntent]:
    """Convert a position-target series into transaction intents."""
    intents: List[TransactionIntent] = []
    prev_target = 0

    for i in range(len(df)):
        target = int(signals.iloc[i]) if pd.notna(signals.iloc[i]) else 0
        ts = pd.Timestamp(df["Date"].iloc[i]).to_pydatetime()

        if target == prev_target:
            continue

        if prev_target != 0:
            intents.append(
                TransactionIntent(
                    timestamp=ts,
                    asset=symbol,
                    direction=Direction.EXIT,
                    leverage=leverage,
                    sizing_pct=sizing_pct,
                )
            )

        if target == 1:
            intents.append(
                TransactionIntent(
                    timestamp=ts,
                    asset=symbol,
                    direction=Direction.LONG,
                    leverage=leverage,
                    sizing_pct=sizing_pct,
                )
            )
        elif target == -1:
            intents.append(
                TransactionIntent(
                    timestamp=ts,
                    asset=symbol,
                    direction=Direction.SHORT,
                    leverage=leverage,
                    sizing_pct=sizing_pct,
                )
            )

        prev_target = target

    return intents
