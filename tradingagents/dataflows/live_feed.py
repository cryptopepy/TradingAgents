"""Unified live market feed router — spot prices, metadata, and intraday tickers.

Vendor order for spot: CryptoCompare → CoinGecko → Binance (live_mode) → localized
mock ticker anchored on the last known good price (mutates via DummyPriceFeed).

API keys: ``CRYPTOCOMPARE_API_KEY``, ``COINGECKO_API_KEY`` (also
``TRADINGAGENTS_*`` aliases).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import pandas as pd
import requests

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.crypto_common import env_api_key
from tradingagents.dataflows.dummy_feed import DummyPriceFeed
from tradingagents.dataflows.symbol_utils import parse_crypto_pair


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

logger = logging.getLogger(__name__)


@dataclass
class LiveFeedCredentials:
    """Resolved vendor API keys from the environment."""

    cryptocompare: str | None = field(
        default_factory=lambda: env_api_key(
            "CRYPTOCOMPARE_API_KEY", "TRADINGAGENTS_CRYPTOCOMPARE_API_KEY"
        )
    )
    coingecko: str | None = field(
        default_factory=lambda: env_api_key(
            "COINGECKO_API_KEY", "TRADINGAGENTS_COINGECKO_API_KEY"
        )
    )


@dataclass
class MarketMetadata:
    """CoinGecko-derived asset and global market context."""

    symbol: str
    name: str | None = None
    coin_id: str | None = None
    circulating_supply: float | None = None
    market_cap_usd: float | None = None
    global_market_cap_usd: float | None = None
    source: str = "coingecko"


class LiveFeedRouter:
    """Stateful router with anchor cache for resilient mock fallback."""

    def __init__(self, config: Optional[dict] = None) -> None:
        self.config = config or get_config()
        self.credentials = LiveFeedCredentials()
        self._anchors: dict[str, float] = {}
        self._mock_feeds: dict[str, DummyPriceFeed] = {}

    def _remember_anchor(self, symbol: str, price: float) -> None:
        if price > 0:
            self._anchors[symbol] = price

    def _localized_mock_ticker(self, symbol: str) -> LivePrice:
        """Mutating synthetic quote from the last known anchor."""
        anchor = self._anchors.get(symbol)
        if anchor is None:
            from tradingagents.backtest.engine import LookbackWindow, fetch_historical_crypto

            end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            try:
                df = fetch_historical_crypto(symbol, end, LookbackWindow.H24)
                anchor = float(df["Close"].iloc[-1]) if not df.empty else 1.0
            except Exception as exc:
                logger.warning("Mock anchor fetch failed for %s: %s", symbol, exc)
                anchor = 1.0
            self._remember_anchor(symbol, anchor)

        feed = self._mock_feeds.get(symbol)
        if feed is None:
            feed = DummyPriceFeed(anchor_price=anchor, symbol=symbol)
            self._mock_feeds[symbol] = feed
        ticker = feed.fetch_ticker()
        price = float(ticker["last"])
        self._remember_anchor(symbol, price)
        return LivePrice(
            symbol=symbol,
            price=price,
            source=PriceSource.PLACEHOLDER,
            timestamp=datetime.now(timezone.utc),
        )

    def _is_rate_or_network_error(self, exc: Exception) -> bool:
        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            return True
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            return exc.response.status_code in (429, 502, 503, 504)
        return False

    def fetch_spot(
        self,
        symbol: str,
        *,
        use_binance: bool | None = None,
    ) -> LivePrice:
        """Spot price with vendor chain and localized mock on 429/network failure."""
        from tradingagents.dataflows.cryptocompare import fetch_spot_price as _fetch_cryptocompare_spot
        from tradingagents.dataflows.coingecko import get_simple_price as _fetch_coingecko_spot

        def _fetch_binance_spot(sym: str) -> float | None:
            try:
                import ccxt

                pair = parse_crypto_pair(sym)
                exchange = ccxt.binance({"enableRateLimit": True})
                ticker = exchange.fetch_ticker(pair.binance_symbol)
                return float(ticker["last"])
            except Exception:
                return None
        from tradingagents.backtest.engine import is_live_mode

        now = datetime.now(timezone.utc)
        vendors = (
            (_fetch_cryptocompare_spot, PriceSource.CRYPTOCOMPARE),
            (_fetch_coingecko_spot, PriceSource.COINGECKO),
        )
        for fetcher, source in vendors:
            try:
                price = fetcher(symbol)
                if price is not None and price > 0:
                    self._remember_anchor(symbol, price)
                    return LivePrice(symbol=symbol, price=price, source=source, timestamp=now)
            except Exception as exc:
                if self._is_rate_or_network_error(exc):
                    logger.warning("%s rate/network error for %s: %s", source.value, symbol, exc)
                    return self._localized_mock_ticker(symbol)
                logger.debug("%s fetch failed for %s: %s", source.value, symbol, exc)

        live_flag = use_binance if use_binance is not None else is_live_mode(self.config)
        if live_flag:
            try:
                price = _fetch_binance_spot(symbol)
                if price is not None and price > 0:
                    self._remember_anchor(symbol, price)
                    return LivePrice(symbol=symbol, price=price, source=PriceSource.BINANCE, timestamp=now)
            except Exception as exc:
                if self._is_rate_or_network_error(exc):
                    return self._localized_mock_ticker(symbol)

        return self._localized_mock_ticker(symbol)

    def fetch_metadata(self, symbol: str) -> MarketMetadata:
        """CoinGecko metadata: name, circulating supply, asset and global market cap."""
        from tradingagents.dataflows.coingecko import resolve_coin_id
        from tradingagents.dataflows.coingecko import _api_base, _headers
        from tradingagents.dataflows.crypto_common import http_get_json

        pair = parse_crypto_pair(symbol)
        meta = MarketMetadata(symbol=pair.display)
        coin_id = resolve_coin_id(pair.base)
        if not coin_id:
            return meta

        meta.coin_id = coin_id
        try:
            data = http_get_json(
                f"{_api_base()}/coins/{coin_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "true",
                    "community_data": "false",
                    "developer_data": "false",
                },
                headers=_headers(),
            )
            md = data.get("market_data") or {}
            meta.name = data.get("name")
            cs = md.get("circulating_supply")
            meta.circulating_supply = float(cs) if cs is not None else None
            mc = md.get("market_cap", {}).get("usd")
            meta.market_cap_usd = float(mc) if mc is not None else None
        except Exception as exc:
            logger.debug("CoinGecko metadata failed for %s: %s", symbol, exc)

        try:
            global_data = http_get_json(f"{_api_base()}/global", headers=_headers())
            total = (global_data.get("data") or {}).get("total_market_cap", {}).get("usd")
            meta.global_market_cap_usd = float(total) if total is not None else None
        except Exception as exc:
            logger.debug("CoinGecko global market cap failed: %s", exc)

        return meta

    def fetch_intraday_ticks(
        self,
        symbol: str,
        *,
        interval: str = "minute",
        limit: int = 60,
    ) -> pd.DataFrame:
        """CryptoCompare minute or hourly OHLCV (REST)."""
        from tradingagents.dataflows.cryptocompare import _BASE_URL, _headers
        from tradingagents.dataflows.crypto_common import http_get_json

        pair = parse_crypto_pair(symbol)
        fsym = pair.base
        tsym = pair.quote if pair.quote not in ("USDT", "USDC", "BUSD") else "USD"
        endpoint = "histominute" if interval == "minute" else "histohour"
        try:
            data = http_get_json(
                f"{_BASE_URL}/data/v2/{endpoint}",
                params={"fsym": fsym, "tsym": tsym, "limit": limit},
                headers=_headers(),
            )
        except Exception as exc:
            if self._is_rate_or_network_error(exc):
                quote = self.fetch_spot(symbol)
                now = datetime.now(timezone.utc)
                return pd.DataFrame(
                    {
                        "Date": [now],
                        "Open": [quote.price],
                        "High": [quote.price],
                        "Low": [quote.price],
                        "Close": [quote.price],
                        "Volume": [0.0],
                    }
                )
            raise

        raw = (data.get("Data") or {}).get("Data") or []
        if not raw:
            quote = self.fetch_spot(symbol)
            now = datetime.now(timezone.utc)
            return pd.DataFrame(
                {
                    "Date": [now],
                    "Open": [quote.price],
                    "High": [quote.price],
                    "Low": [quote.price],
                    "Close": [quote.price],
                    "Volume": [0.0],
                }
            )

        df = pd.DataFrame(raw)
        df["Date"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volumeto": "Volume",
            }
        )
        for col in ("Open", "High", "Low", "Close", "Volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])


_default_router: LiveFeedRouter | None = None


def get_live_feed_router(config: Optional[dict] = None) -> LiveFeedRouter:
    global _default_router
    if config is not None:
        return LiveFeedRouter(config)
    if _default_router is None:
        _default_router = LiveFeedRouter()
    return _default_router


def fetch_live_spot_price(
    symbol: str,
    config: Optional[dict] = None,
    *,
    use_binance: bool | None = None,
) -> LivePrice:
    """Module-level spot fetch via the unified router."""
    return get_live_feed_router(config).fetch_spot(symbol, use_binance=use_binance)


def fetch_live_spot_price_value(symbol: str, config: Optional[dict] = None) -> float:
    return fetch_live_spot_price(symbol, config).price


def fetch_market_metadata(symbol: str, config: Optional[dict] = None) -> MarketMetadata:
    return get_live_feed_router(config).fetch_metadata(symbol)


def fetch_intraday_ticks(
    symbol: str,
    *,
    interval: str = "minute",
    limit: int = 60,
    config: Optional[dict] = None,
) -> pd.DataFrame:
    return get_live_feed_router(config).fetch_intraday_ticks(
        symbol, interval=interval, limit=limit
    )
