"""Mock live price feed for paper-trading when LIVE_MODE is off."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class DummyPriceFeed:
    """Polls a synthetic price that drifts from a historical anchor."""

    anchor_price: float
    symbol: str
    drift_pct: float = 0.001
    seed: Optional[int] = None
    _price: float = field(init=False)
    _rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self._price = float(self.anchor_price)
        self._rng = random.Random(self.seed)

    def fetch_ticker(self) -> dict:
        """Return a ccxt-like ticker dict with a mutating last price."""
        move = self._rng.uniform(-self.drift_pct, self.drift_pct)
        self._price *= 1 + move
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return {
            "symbol": self.symbol,
            "last": self._price,
            "close": self._price,
            "timestamp": now_ms,
            "datetime": datetime.now(timezone.utc).isoformat(),
            "info": {"source": "dummy_feed", "anchor": self.anchor_price},
        }

    @property
    def last_price(self) -> float:
        return self._price
