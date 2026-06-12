"""Simulated order matcher for paper trading (no real exchange orders)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from tradingagents.backtest.portfolio import Direction, TransactionIntent, VirtualPortfolio
from tradingagents.dataflows.dummy_feed import DummyPriceFeed

logger = logging.getLogger(__name__)

PriceFeed = Callable[[str], float]


@dataclass
class FillRecord:
    intent: TransactionIntent
    fill_price: float
    slippage_bps: float
    filled_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SimulatedMatcher:
    """Broker-like API: submit intents, simulate fills with slippage."""

    slippage_bps: float = 5.0
    portfolio: VirtualPortfolio = field(default_factory=VirtualPortfolio)
    price_feed: Optional[PriceFeed] = None
    pending_limits: List[TransactionIntent] = field(default_factory=list)
    fills: List[FillRecord] = field(default_factory=list)

    def _resolve_price(self, asset: str, reference_price: Optional[float] = None) -> float:
        if reference_price is not None:
            return reference_price
        if self.price_feed is not None:
            return self.price_feed(asset)
        raise ValueError(f"No price available for {asset}")

    def _apply_slippage(self, price: float, direction: Direction) -> float:
        slip = self.slippage_bps / 10_000.0
        if direction == Direction.LONG:
            return price * (1.0 + slip)
        if direction == Direction.SHORT:
            return price * (1.0 - slip)
        return price

    def submit_intent(
        self,
        intent: TransactionIntent,
        *,
        reference_price: Optional[float] = None,
        order_type: str = "market",
        limit_price: Optional[float] = None,
    ) -> Optional[FillRecord]:
        """Submit an intent; market orders fill immediately, limits queue as stub."""
        if order_type == "limit":
            intent_copy = intent.model_copy()
            self.pending_limits.append(intent_copy)
            logger.debug("Queued limit intent for %s at %s", intent.asset, limit_price)
            return None

        raw_price = self._resolve_price(intent.asset, reference_price)
        fill_price = self._apply_slippage(raw_price, intent.direction)
        self.portfolio.apply_intent(intent, fill_price)
        record = FillRecord(intent=intent, fill_price=fill_price, slippage_bps=self.slippage_bps)
        self.fills.append(record)
        return record

    def check_pending_limits(self, asset: str, price: float) -> List[FillRecord]:
        """Stub limit-order simulation — fills when price crosses limit."""
        filled: List[FillRecord] = []
        remaining: List[TransactionIntent] = []
        for intent in self.pending_limits:
            if intent.asset != asset:
                remaining.append(intent)
                continue
            record = self.submit_intent(intent, reference_price=price)
            if record:
                filled.append(record)
        self.pending_limits = remaining
        return filled

    def mark_to_market(self, prices: Dict[str, float]) -> None:
        self.portfolio.mark_to_market(prices)


def build_price_feed(
    symbol: str,
    *,
    live_mode: bool = False,
    anchor_price: float = 1.0,
) -> PriceFeed:
    """Build a price feed for paper mode (dummy) or live quote lookup (no orders)."""
    if live_mode:
        from tradingagents.backtest.engine import fetch_live_price

        return lambda asset: fetch_live_price(asset)

    feed = DummyPriceFeed(anchor_price=anchor_price, symbol=symbol, seed=0)

    def _feed(asset: str) -> float:
        return float(feed.fetch_ticker()["last"])

    return _feed
