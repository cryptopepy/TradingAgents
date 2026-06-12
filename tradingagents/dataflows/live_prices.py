"""Unified live spot price fetching with vendor fallback.

Tries CryptoCompare and CoinGecko (API keys from .env), then ccxt Binance
when ``live_mode`` is on, then a historical placeholder via DummyPriceFeed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.symbol_utils import parse_crypto_pair

logger = logging.getLogger(__name__)


class PriceSource(str, Enum):
    CRYPTOCOMPARE = "cryptocompare"
    COINGECKO = "coingecko"
    BINANCE = "binance"
    PLACEHOLDER = "placeholder"


@dataclass(frozen=True)
class LivePrice:
    """Spot price quote with provenance."""

    symbol: str
    price: float
    source: PriceSource
    timestamp: datetime


def _fetch_cryptocompare_spot(symbol: str) -> float | None:
    from tradingagents.dataflows.cryptocompare import fetch_spot_price

    return fetch_spot_price(symbol)


def _fetch_coingecko_spot(symbol: str) -> float | None:
    from tradingagents.dataflows.coingecko import get_simple_price

    return get_simple_price(symbol)


def _fetch_binance_spot(symbol: str) -> float | None:
    try:
        import ccxt

        pair = parse_crypto_pair(symbol)
        exchange = ccxt.binance({"enableRateLimit": True})
        ticker = exchange.fetch_ticker(pair.binance_symbol)
        return float(ticker["last"])
    except Exception as exc:
        logger.debug("Binance spot fetch failed for %s: %s", symbol, exc)
        return None


def _fetch_placeholder_spot(symbol: str, config: Optional[dict] = None) -> float:
    """Anchor from last historical bar, then one dummy-feed step."""
    from tradingagents.backtest.engine import LookbackWindow, fetch_historical_crypto
    from tradingagents.dataflows.dummy_feed import DummyPriceFeed

    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        df = fetch_historical_crypto(symbol, end, LookbackWindow.H24)
        anchor = float(df["Close"].iloc[-1]) if not df.empty else 1.0
    except Exception as exc:
        logger.warning("Placeholder anchor fetch failed for %s: %s", symbol, exc)
        anchor = 1.0
    feed = DummyPriceFeed(anchor_price=anchor, symbol=symbol)
    return float(feed.fetch_ticker()["last"])


def fetch_live_spot_price(
    symbol: str,
    config: Optional[dict] = None,
    *,
    use_binance: bool | None = None,
) -> LivePrice:
    """Fetch current spot price with vendor fallback chain.

    Order: CryptoCompare → CoinGecko → Binance (when live) → placeholder.
    """
    cfg = config or get_config()
    now = datetime.now(timezone.utc)

    for fetcher, source in (
        (_fetch_cryptocompare_spot, PriceSource.CRYPTOCOMPARE),
        (_fetch_coingecko_spot, PriceSource.COINGECKO),
    ):
        try:
            price = fetcher(symbol)
            if price is not None and price > 0:
                return LivePrice(symbol=symbol, price=price, source=source, timestamp=now)
        except Exception as exc:
            logger.debug("%s fetch failed for %s: %s", source.value, symbol, exc)

    live_flag = use_binance
    if live_flag is None:
        from tradingagents.backtest.engine import is_live_mode

        live_flag = is_live_mode(cfg)

    if live_flag:
        price = _fetch_binance_spot(symbol)
        if price is not None and price > 0:
            return LivePrice(symbol=symbol, price=price, source=PriceSource.BINANCE, timestamp=now)

    price = _fetch_placeholder_spot(symbol, cfg)
    return LivePrice(symbol=symbol, price=price, source=PriceSource.PLACEHOLDER, timestamp=now)


def fetch_live_spot_price_value(symbol: str, config: Optional[dict] = None) -> float:
    """Convenience wrapper returning only the numeric price."""
    return fetch_live_spot_price(symbol, config).price
