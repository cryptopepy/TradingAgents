"""CoinGecko API — coin metadata, market data, and simple prices."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from functools import lru_cache
from typing import Annotated

import requests

from .crypto_common import env_api_key, no_data_message
from .symbol_utils import CryptoPair, parse_crypto_pair

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.coingecko.com/api/v3"
_PRO_URL = "https://pro-api.coingecko.com/api/v3"

# Trading-pair quotes → CoinGecko vs_currencies / market_data keys.
_QUOTE_TO_VS = {
    "USDT": "usd",
    "USDC": "usd",
    "BUSD": "usd",
    "USD": "usd",
    "EUR": "eur",
    "GBP": "gbp",
    "BTC": "btc",
    "ETH": "eth",
}

# Well-known symbol → CoinGecko id shortcuts (avoids search on hot path).
_SYMBOL_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "NEAR": "near",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "SUI": "sui",
    "BNB": "binancecoin",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
}


class CoinGeckoAPIError(Exception):
    """CoinGecko API failure with a user-facing message."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: int | None = None,
    ):
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


def _api_key() -> str | None:
    return env_api_key("COINGECKO_API_KEY", "TRADINGAGENTS_COINGECKO_API_KEY")


def _configured_tier() -> str:
    return os.environ.get("COINGECKO_API_TIER", "auto").strip().lower()


@lru_cache(maxsize=1)
def _detect_api_tier(key: str) -> str:
    """Probe whether *key* is a Pro or Demo CoinGecko API key."""
    try:
        resp = requests.get(
            f"{_PRO_URL}/ping",
            headers={"x-cg-pro-api-key": key},
            timeout=15,
        )
        if resp.status_code == 200:
            return "pro"
        body = resp.json() if resp.content else {}
        status = body.get("status") or {}
        msg = str(status.get("error_message") or body.get("error_message") or "")
        if body.get("error_code") == 10011 or "Demo API key" in msg:
            return "demo"
    except Exception as exc:
        logger.debug("CoinGecko tier probe failed, defaulting to demo: %s", exc)
    return "demo"


def api_tier() -> str:
    """Return ``none``, ``demo``, or ``pro`` for the configured CoinGecko key."""
    key = _api_key()
    if not key:
        return "none"
    tier = _configured_tier()
    if tier in {"demo", "pro"}:
        return tier
    return _detect_api_tier(key)


def is_pro_tier() -> bool:
    return api_tier() == "pro"


def _api_base() -> str:
    return _PRO_URL if api_tier() == "pro" else _BASE_URL


def _headers() -> dict[str, str]:
    key = _api_key()
    if not key:
        return {}
    if api_tier() == "pro":
        return {"x-cg-pro-api-key": key}
    return {"x-cg-demo-api-key": key}


def _vs_currency(quote: str) -> str:
    """Map a trading-pair quote (USDT) to a CoinGecko vs_currency (usd)."""
    return _QUOTE_TO_VS.get(quote.upper(), quote.lower())


def _parse_error_message(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300] or resp.reason
    status = body.get("status") or {}
    return str(
        status.get("error_message")
        or body.get("error_message")
        or body.get("error")
        or resp.text[:300]
        or resp.reason
    )


def _parse_error_code(resp: requests.Response) -> int | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    status = body.get("status") or {}
    code = status.get("error_code") or body.get("error_code")
    return int(code) if code is not None else None


def _coingecko_get(path: str, *, params: dict | None = None) -> dict | list:
    """GET JSON from CoinGecko with tier-aware auth and actionable errors."""
    url = f"{_api_base()}{path}"
    try:
        resp = requests.get(url, params=params, headers=_headers(), timeout=30)
    except requests.exceptions.RequestException as exc:
        raise CoinGeckoAPIError(f"Network error contacting CoinGecko: {exc}") from exc

    if resp.status_code == 429:
        raise CoinGeckoAPIError(
            "CoinGecko rate limit exceeded (429). Retry later or set COINGECKO_API_KEY "
            "for higher limits.",
            status_code=429,
            error_code=429,
        )

    if resp.status_code == 401:
        detail = _parse_error_message(resp)
        raise CoinGeckoAPIError(
            f"CoinGecko authentication failed (401): {detail}. "
            "Verify COINGECKO_API_KEY and COINGECKO_API_TIER (demo|pro|auto).",
            status_code=401,
            error_code=_parse_error_code(resp),
        )

    if resp.status_code == 400:
        detail = _parse_error_message(resp)
        code = _parse_error_code(resp)
        hint = ""
        if code == 10011 or "Demo API key" in detail:
            hint = " Set COINGECKO_API_TIER=demo (or remove the key for anonymous access)."
        raise CoinGeckoAPIError(
            f"CoinGecko bad request (400): {detail}.{hint}",
            status_code=400,
            error_code=code,
        )

    if resp.status_code == 404:
        detail = _parse_error_message(resp)
        raise CoinGeckoAPIError(
            f"CoinGecko endpoint not found (404): {detail}",
            status_code=404,
            error_code=_parse_error_code(resp),
        )

    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        detail = _parse_error_message(resp)
        raise CoinGeckoAPIError(
            f"CoinGecko HTTP {resp.status_code}: {detail}",
            status_code=resp.status_code,
            error_code=_parse_error_code(resp),
        ) from exc

    try:
        return resp.json()
    except ValueError as exc:
        raise CoinGeckoAPIError(
            "CoinGecko returned a non-JSON response (schema mismatch)."
        ) from exc


def _market_value(md: dict, field: str, vs: str):
    block = md.get(field) or {}
    if not isinstance(block, dict):
        return None
    return block.get(vs)


@lru_cache(maxsize=256)
def resolve_coin_id(base_symbol: str) -> str | None:
    """Map a base symbol (BTC) to a CoinGecko coin id."""
    sym = base_symbol.upper()
    if sym in _SYMBOL_TO_ID:
        return _SYMBOL_TO_ID[sym]
    try:
        data = _coingecko_get("/search", params={"query": sym})
        if not isinstance(data, dict):
            raise CoinGeckoAPIError("CoinGecko /search response schema mismatch (expected object).")
        coins = data.get("coins") or []
        for coin in coins:
            if str(coin.get("symbol", "")).upper() == sym:
                return coin.get("id")
        if coins:
            return coins[0].get("id")
    except CoinGeckoAPIError as exc:
        logger.warning("CoinGecko search failed for %s: %s", sym, exc)
    except Exception as exc:
        logger.warning("CoinGecko search failed for %s: %s", sym, exc)
    return None


def get_coin_identity(pair: CryptoPair) -> dict:
    """Return name, categories, and market rank for a base asset."""
    coin_id = resolve_coin_id(pair.base)
    if not coin_id:
        return {}
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
        if not isinstance(data, dict):
            raise CoinGeckoAPIError("CoinGecko /coins response schema mismatch (expected object).")
        md = data.get("market_data") or {}
        identity = {
            "name": data.get("name"),
            "symbol": data.get("symbol", "").upper(),
            "coin_id": coin_id,
            "categories": ", ".join(data.get("categories") or [])[:200],
            "market_cap_rank": md.get("market_cap_rank"),
        }
        return {k: v for k, v in identity.items() if v is not None}
    except CoinGeckoAPIError as exc:
        logger.debug("CoinGecko identity lookup failed for %s: %s", pair.base, exc)
        return {}
    except Exception as exc:
        logger.debug("CoinGecko identity lookup failed for %s: %s", pair.base, exc)
        return {}


def get_crypto_fundamentals(
    symbol: Annotated[str, "crypto pair e.g. BTC/USDT"],
    curr_date: Annotated[str, "analysis date YYYY-MM-DD"],
) -> str:
    """Comprehensive on-chain/market fundamentals from CoinGecko."""
    try:
        pair = parse_crypto_pair(symbol)
    except ValueError as exc:
        return no_data_message(symbol, str(exc))

    coin_id = resolve_coin_id(pair.base)
    if not coin_id:
        return no_data_message(symbol, "unknown base asset on CoinGecko")

    vs = _vs_currency(pair.quote)
    try:
        data = _coingecko_get(
            f"/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "true",
                "developer_data": "true",
            },
        )
        if not isinstance(data, dict):
            raise CoinGeckoAPIError("CoinGecko /coins response schema mismatch (expected object).")
    except CoinGeckoAPIError as exc:
        return no_data_message(symbol, f"CoinGecko error: {exc}")

    md = data.get("market_data") or {}
    comm = data.get("community_data") or {}
    dev = data.get("developer_data") or {}
    quote_label = pair.quote if vs == pair.quote.lower() else f"{pair.quote} (via {vs.upper()})"

    lines = [
        f"# Crypto fundamentals for {pair.display} (CoinGecko: {coin_id})",
        f"# As of analysis date: {curr_date}",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Name: {data.get('name', 'N/A')}",
        f"Categories: {', '.join(data.get('categories') or []) or 'N/A'}",
        "",
        "## Market metrics",
        f"Current price ({quote_label}): {_market_value(md, 'current_price', vs) or 'N/A'}",
        f"Market cap: {_market_value(md, 'market_cap', vs) or 'N/A'}",
        f"Fully diluted valuation (FDV): {_market_value(md, 'fully_diluted_valuation', vs) or 'N/A'}",
        f"24h volume: {_market_value(md, 'total_volume', vs) or 'N/A'}",
        f"Circulating supply: {md.get('circulating_supply', 'N/A')}",
        f"Total supply: {md.get('total_supply', 'N/A')}",
        f"Max supply: {md.get('max_supply', 'N/A')}",
        f"Market cap rank: {md.get('market_cap_rank', 'N/A')}",
        "",
        "## Tokenomics / supply",
        f"ATH: {_market_value(md, 'ath', vs) or 'N/A'}",
        f"ATL: {_market_value(md, 'atl', vs) or 'N/A'}",
        "",
        "## Community (proxy for engagement)",
        f"Twitter followers: {comm.get('twitter_followers', 'N/A')}",
        f"Reddit subscribers: {comm.get('reddit_subscribers', 'N/A')}",
        "",
        "## Developer activity",
        f"GitHub stars: {(dev.get('stars') or 'N/A')}",
        f"GitHub forks: {(dev.get('forks') or 'N/A')}",
        f"Commit count (4 weeks): {(dev.get('commit_count_4_weeks') or 'N/A')}",
        "",
        "Note: TVL and active addresses require chain-specific indexers; "
        "use get_onchain_metrics for supplemental data when available.",
    ]
    return "\n".join(lines)


def get_tokenomics(
    symbol: Annotated[str, "crypto pair e.g. ETH/USDC"],
    curr_date: Annotated[str, "analysis date YYYY-MM-DD"] = "",
) -> str:
    """Token supply, FDV, and emission-related metrics."""
    try:
        pair = parse_crypto_pair(symbol)
    except ValueError as exc:
        return no_data_message(symbol, str(exc))

    coin_id = resolve_coin_id(pair.base)
    if not coin_id:
        return no_data_message(symbol, "unknown base asset")

    vs = _vs_currency(pair.quote)
    try:
        data = _coingecko_get(
            f"/coins/{coin_id}",
            params={"localization": "false", "tickers": "false", "market_data": "true"},
        )
        if not isinstance(data, dict):
            raise CoinGeckoAPIError("CoinGecko /coins response schema mismatch (expected object).")
    except CoinGeckoAPIError as exc:
        return no_data_message(symbol, str(exc))

    md = data.get("market_data") or {}
    return "\n".join([
        f"# Tokenomics for {pair.display}",
        f"Analysis date: {curr_date or 'N/A'}",
        f"Circulating supply: {md.get('circulating_supply', 'N/A')}",
        f"Total supply: {md.get('total_supply', 'N/A')}",
        f"Max supply: {md.get('max_supply', 'N/A')}",
        f"Market cap: {_market_value(md, 'market_cap', vs) or 'N/A'}",
        f"FDV: {_market_value(md, 'fully_diluted_valuation', vs) or 'N/A'}",
        f"MC/FDV ratio: {_mc_fdv_ratio(md, vs)}",
    ])


def _mc_fdv_ratio(md: dict, vs: str) -> str:
    mc = _market_value(md, "market_cap", vs)
    fdv = _market_value(md, "fully_diluted_valuation", vs)
    if mc and fdv and fdv > 0:
        return f"{mc / fdv:.2%}"
    return "N/A"


def _parse_simple_price(data: dict, coin_id: str, vs: str) -> float:
    coin = data.get(coin_id)
    if not isinstance(coin, dict):
        raise CoinGeckoAPIError(
            f"Schema mismatch: coin id '{coin_id}' missing from /simple/price response."
        )
    if vs not in coin or coin[vs] is None:
        raise CoinGeckoAPIError(
            f"Quote currency '{vs}' unavailable in CoinGecko /simple/price response. "
            "Stablecoin quotes (USDT/USDC) are mapped to USD; verify the pair is supported."
        )
    return float(coin[vs])


def get_simple_price(symbol: str) -> float | None:
    """Latest spot price for the base asset in the pair's quote currency."""
    try:
        pair = parse_crypto_pair(symbol)
    except ValueError:
        return None
    coin_id = resolve_coin_id(pair.base)
    if not coin_id:
        return None
    vs = _vs_currency(pair.quote)
    try:
        data = _coingecko_get(
            "/simple/price",
            params={"ids": coin_id, "vs_currencies": vs},
        )
        if not isinstance(data, dict):
            raise CoinGeckoAPIError("CoinGecko /simple/price response schema mismatch (expected object).")
        return _parse_simple_price(data, coin_id, vs)
    except CoinGeckoAPIError as exc:
        logger.debug("CoinGecko simple price failed for %s: %s", symbol, exc)
        return None
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("CoinGecko simple price parse failed for %s: %s", symbol, exc)
        return None


def fetch_coin_news(coin_id: str, *, per_page: int = 10) -> list[dict]:
    """Fetch CoinGecko news articles for a coin (Pro API only)."""
    if not is_pro_tier():
        raise CoinGeckoAPIError(
            "CoinGecko /news requires a Pro API key (COINGECKO_API_TIER=pro).",
            error_code=10005,
        )
    data = _coingecko_get(
        "/news",
        params={"coin_id": coin_id, "per_page": per_page, "type": "news"},
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        articles = data.get("data") or data.get("news")
        if isinstance(articles, list):
            return articles
    raise CoinGeckoAPIError("CoinGecko /news response schema mismatch (expected list).")
