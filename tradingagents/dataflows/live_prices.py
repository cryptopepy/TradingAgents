"""Live spot prices — thin compatibility layer over ``live_feed``.

Prefer ``tradingagents.dataflows.live_feed`` for metadata and intraday ticks.
"""

from __future__ import annotations

from typing import Optional

from tradingagents.dataflows.live_feed import (
    LiveFeedRouter,
    LivePrice,
    MarketMetadata,
    PriceSource,
    fetch_intraday_ticks,
    fetch_live_spot_price,
    fetch_live_spot_price_value,
    fetch_market_metadata,
    get_live_feed_router,
)

__all__ = [
    "LiveFeedRouter",
    "LivePrice",
    "MarketMetadata",
    "PriceSource",
    "fetch_intraday_ticks",
    "fetch_live_spot_price",
    "fetch_live_spot_price_value",
    "fetch_market_metadata",
    "get_live_feed_router",
]


def _fetch_cryptocompare_spot(symbol: str) -> float | None:
    from tradingagents.dataflows.cryptocompare import fetch_spot_price

    return fetch_spot_price(symbol)


def _fetch_coingecko_spot(symbol: str) -> float | None:
    from tradingagents.dataflows.coingecko import get_simple_price

    return get_simple_price(symbol)


def _fetch_binance_spot(symbol: str) -> float | None:
    try:
        import ccxt

        from tradingagents.dataflows.symbol_utils import parse_crypto_pair

        pair = parse_crypto_pair(symbol)
        exchange = ccxt.binance({"enableRateLimit": True})
        ticker = exchange.fetch_ticker(pair.binance_symbol)
        return float(ticker["last"])
    except Exception:
        return None


def _fetch_placeholder_spot(symbol: str, config: Optional[dict] = None) -> float:
    return fetch_live_spot_price(symbol, config, use_binance=False).price
