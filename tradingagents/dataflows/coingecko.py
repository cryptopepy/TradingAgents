"""CoinGecko API — coin metadata, market data, and simple prices."""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from typing import Annotated

from .crypto_common import env_api_key, http_get_json, no_data_message
from .symbol_utils import CryptoPair, parse_crypto_pair

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.coingecko.com/api/v3"
_PRO_URL = "https://pro-api.coingecko.com/api/v3"

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


def _api_base() -> str:
    if env_api_key("COINGECKO_API_KEY", "TRADINGAGENTS_COINGECKO_API_KEY"):
        return _PRO_URL
    return _BASE_URL


def _headers() -> dict:
    key = env_api_key("COINGECKO_API_KEY", "TRADINGAGENTS_COINGECKO_API_KEY")
    if key:
        return {"x-cg-pro-api-key": key}
    return {}


@lru_cache(maxsize=256)
def resolve_coin_id(base_symbol: str) -> str | None:
    """Map a base symbol (BTC) to a CoinGecko coin id."""
    sym = base_symbol.upper()
    if sym in _SYMBOL_TO_ID:
        return _SYMBOL_TO_ID[sym]
    try:
        data = http_get_json(
            f"{_api_base()}/search",
            params={"query": sym},
            headers=_headers(),
        )
        coins = data.get("coins") or []
        for coin in coins:
            if str(coin.get("symbol", "")).upper() == sym:
                return coin.get("id")
        if coins:
            return coins[0].get("id")
    except Exception as exc:
        logger.warning("CoinGecko search failed for %s: %s", sym, exc)
    return None


def get_coin_identity(pair: CryptoPair) -> dict:
    """Return name, categories, and market rank for a base asset."""
    coin_id = resolve_coin_id(pair.base)
    if not coin_id:
        return {}
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
        identity = {
            "name": data.get("name"),
            "symbol": data.get("symbol", "").upper(),
            "coin_id": coin_id,
            "categories": ", ".join(data.get("categories") or [])[:200],
            "market_cap_rank": md.get("market_cap_rank"),
        }
        return {k: v for k, v in identity.items() if v is not None}
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

    try:
        data = http_get_json(
            f"{_api_base()}/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "true",
                "developer_data": "true",
            },
            headers=_headers(),
        )
    except Exception as exc:
        return no_data_message(symbol, f"CoinGecko error: {exc}")

    md = data.get("market_data") or {}
    comm = data.get("community_data") or {}
    dev = data.get("developer_data") or {}

    lines = [
        f"# Crypto fundamentals for {pair.display} (CoinGecko: {coin_id})",
        f"# As of analysis date: {curr_date}",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Name: {data.get('name', 'N/A')}",
        f"Categories: {', '.join(data.get('categories') or []) or 'N/A'}",
        "",
        "## Market metrics",
        f"Current price ({pair.quote}): {md.get('current_price', {}).get(pair.quote.lower(), 'N/A')}",
        f"Market cap: {md.get('market_cap', {}).get(pair.quote.lower(), 'N/A')}",
        f"Fully diluted valuation (FDV): {md.get('fully_diluted_valuation', {}).get(pair.quote.lower(), 'N/A')}",
        f"24h volume: {md.get('total_volume', {}).get(pair.quote.lower(), 'N/A')}",
        f"Circulating supply: {md.get('circulating_supply', 'N/A')}",
        f"Total supply: {md.get('total_supply', 'N/A')}",
        f"Max supply: {md.get('max_supply', 'N/A')}",
        f"Market cap rank: {md.get('market_cap_rank', 'N/A')}",
        "",
        "## Tokenomics / supply",
        f"ATH: {md.get('ath', {}).get(pair.quote.lower(), 'N/A')}",
        f"ATL: {md.get('atl', {}).get(pair.quote.lower(), 'N/A')}",
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

    try:
        data = http_get_json(
            f"{_api_base()}/coins/{coin_id}",
            params={"localization": "false", "tickers": "false", "market_data": "true"},
            headers=_headers(),
        )
    except Exception as exc:
        return no_data_message(symbol, str(exc))

    md = data.get("market_data") or {}
    quote = pair.quote.lower()
    return "\n".join([
        f"# Tokenomics for {pair.display}",
        f"Analysis date: {curr_date or 'N/A'}",
        f"Circulating supply: {md.get('circulating_supply', 'N/A')}",
        f"Total supply: {md.get('total_supply', 'N/A')}",
        f"Max supply: {md.get('max_supply', 'N/A')}",
        f"Market cap: {md.get('market_cap', {}).get(quote, 'N/A')}",
        f"FDV: {md.get('fully_diluted_valuation', {}).get(quote, 'N/A')}",
        f"MC/FDV ratio: {_mc_fdv_ratio(md, quote)}",
    ])


def _mc_fdv_ratio(md: dict, quote: str) -> str:
    mc = md.get("market_cap", {}).get(quote)
    fdv = md.get("fully_diluted_valuation", {}).get(quote)
    if mc and fdv and fdv > 0:
        return f"{mc / fdv:.2%}"
    return "N/A"


def get_simple_price(symbol: str) -> float | None:
    """Latest spot price for the base asset in the pair's quote currency."""
    try:
        pair = parse_crypto_pair(symbol)
    except ValueError:
        return None
    coin_id = resolve_coin_id(pair.base)
    if not coin_id:
        return None
    quote = pair.quote.lower()
    try:
        data = http_get_json(
            f"{_api_base()}/simple/price",
            params={"ids": coin_id, "vs_currencies": quote},
            headers=_headers(),
        )
        return float(data[coin_id][quote])
    except Exception:
        return None
