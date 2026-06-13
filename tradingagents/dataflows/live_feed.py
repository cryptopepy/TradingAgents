"""Unified live market feed router — spot prices, metadata, and intraday tickers.

Vendor order for spot: CryptoCompare → ccxt exchanges (Kraken/Coinbase/Binance)
→ CoinGecko → localized mock ticker anchored on the last known good price.

Exchange tickers are preferred over CoinGecko for paper fills — CoinGecko is an
aggregator with slower updates and is kept as a fallback only.

API keys: ``CRYPTOCOMPARE_API_KEY``, ``COINGECKO_API_KEY`` (also
``TRADINGAGENTS_*`` aliases). ccxt order: ``BACKTEST_CCXT_EXCHANGES``.
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

_CCXT_SOURCE_MAP = {
    "kraken": "kraken",
    "coinbase": "coinbase",
    "binance": "binance",
}


class PriceSource(str, Enum):
    CRYPTOCOMPARE = "cryptocompare"
    KRAKEN = "kraken"
    COINBASE = "coinbase"
    BINANCE = "binance"
    COINGECKO = "coingecko"
    PLACEHOLDER = "placeholder"


@dataclass(frozen=True)
class VendorAttempt:
    """One vendor try during a spot price fetch."""

    vendor: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class LivePrice:
    """Spot price quote with provenance."""

    symbol: str
    price: float
    source: PriceSource
    timestamp: datetime
    endpoint: str | None = None


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
        self._last_spot_attempts: list[VendorAttempt] = []

    @property
    def last_spot_attempts(self) -> tuple[VendorAttempt, ...]:
        return tuple(self._last_spot_attempts)

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
            endpoint="localized mock (last anchor)",
        )

    def _attempt_detail(self, exc: Exception) -> str:
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            return f"HTTP {exc.response.status_code}"
        text = str(exc).strip()
        if len(text) > 120:
            return text[:117] + "..."
        return text or exc.__class__.__name__

    def _record_attempt(self, attempts: list[VendorAttempt], vendor: str, ok: bool, detail: str = "") -> None:
        attempts.append(VendorAttempt(vendor=vendor, ok=ok, detail=detail))

    def _price_source_for_exchange(self, exchange_id: str) -> PriceSource:
        label = _CCXT_SOURCE_MAP.get(exchange_id, exchange_id)
        try:
            return PriceSource(label)
        except ValueError:
            return PriceSource.BINANCE

    def fetch_spot(
        self,
        symbol: str,
        *,
        use_binance: bool | None = None,
    ) -> LivePrice:
        """Spot price with vendor chain and localized mock when all vendors fail."""
        from tradingagents.backtest.historical_data import ccxt_exchange_ids, fetch_ccxt_spot_ticker
        from tradingagents.dataflows.cryptocompare import fetch_spot_price as _fetch_cryptocompare_spot
        from tradingagents.dataflows.coingecko import get_simple_price as _fetch_coingecko_spot
        from tradingagents.dataflows.symbol_utils import NoMarketDataError

        now = datetime.now(timezone.utc)
        attempts: list[VendorAttempt] = []

        # 1. CryptoCompare aggregate
        try:
            price = _fetch_cryptocompare_spot(symbol)
            if price is not None and price > 0:
                self._record_attempt(attempts, "cryptocompare", True, "min-api.cryptocompare.com/data/price")
                self._remember_anchor(symbol, price)
                self._last_spot_attempts = attempts
                return LivePrice(
                    symbol=symbol,
                    price=price,
                    source=PriceSource.CRYPTOCOMPARE,
                    timestamp=now,
                    endpoint="cryptocompare /data/price",
                )
            self._record_attempt(attempts, "cryptocompare", False, "no price returned")
        except Exception as exc:
            self._record_attempt(attempts, "cryptocompare", False, self._attempt_detail(exc))

        # 2. ccxt exchange tickers (real-time; preferred over CoinGecko for paper)
        exchange_ids = list(ccxt_exchange_ids(self.config))
        if use_binance is False:
            exchange_ids = [x for x in exchange_ids if x != "binance"]
        for exchange_id in exchange_ids:
            vendor_label = exchange_id
            try:
                price, market_symbol = fetch_ccxt_spot_ticker(symbol, exchange_id)
                self._record_attempt(
                    attempts,
                    vendor_label,
                    True,
                    f"{exchange_id} {market_symbol} ticker",
                )
                self._remember_anchor(symbol, price)
                self._last_spot_attempts = attempts
                return LivePrice(
                    symbol=symbol,
                    price=price,
                    source=self._price_source_for_exchange(exchange_id),
                    timestamp=now,
                    endpoint=f"{exchange_id} {market_symbol}",
                )
            except NoMarketDataError as exc:
                self._record_attempt(attempts, vendor_label, False, exc.detail or str(exc))
            except Exception as exc:
                self._record_attempt(attempts, vendor_label, False, self._attempt_detail(exc))

        # 3. CoinGecko aggregate (slower; metadata-friendly fallback)
        try:
            price = _fetch_coingecko_spot(symbol)
            if price is not None and price > 0:
                self._record_attempt(attempts, "coingecko", True, "api.coingecko.com simple/price")
                self._remember_anchor(symbol, price)
                self._last_spot_attempts = attempts
                return LivePrice(
                    symbol=symbol,
                    price=price,
                    source=PriceSource.COINGECKO,
                    timestamp=now,
                    endpoint="coingecko simple/price",
                )
            self._record_attempt(attempts, "coingecko", False, "no price returned")
        except Exception as exc:
            self._record_attempt(attempts, "coingecko", False, self._attempt_detail(exc))

        self._record_attempt(attempts, "placeholder", False, "all vendors failed")
        self._last_spot_attempts = attempts
        return self._localized_mock_ticker(symbol)

    def fetch_metadata(self, symbol: str) -> MarketMetadata:
        """CoinGecko metadata: name, circulating supply, asset and global market cap."""
        from tradingagents.dataflows.coingecko import CoinGeckoAPIError, _coingecko_get, resolve_coin_id

        pair = parse_crypto_pair(symbol)
        meta = MarketMetadata(symbol=pair.display)
        coin_id = resolve_coin_id(pair.base)
        if not coin_id:
            return meta

        meta.coin_id = coin_id
        try:
            data = _coingecko_get(
                f"/coins/{coin_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "true",
                    "community_data": "false",
                    "developer_data": "false",
                },
            )
            if isinstance(data, dict):
                md = data.get("market_data") or {}
                meta.name = data.get("name")
                cs = md.get("circulating_supply")
                meta.circulating_supply = float(cs) if cs is not None else None
                mc = md.get("market_cap", {}).get("usd")
                meta.market_cap_usd = float(mc) if mc is not None else None
        except CoinGeckoAPIError as exc:
            logger.debug("CoinGecko metadata failed for %s: %s", symbol, exc)

        try:
            global_data = _coingecko_get("/global")
            if isinstance(global_data, dict):
                total = (global_data.get("data") or {}).get("total_market_cap", {}).get("usd")
                meta.global_market_cap_usd = float(total) if total is not None else None
        except CoinGeckoAPIError as exc:
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
            if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
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
