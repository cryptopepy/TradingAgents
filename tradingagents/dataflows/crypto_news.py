"""Crypto-native news aggregation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Annotated, Optional

from .config import get_config
from .coingecko import resolve_coin_id
from .crypto_common import http_get_json, no_data_message
from .cryptocompare import get_cryptocompare_news
from .symbol_utils import parse_crypto_pair

logger = logging.getLogger(__name__)


def get_crypto_news(
    symbol: Annotated[str, "crypto pair e.g. BTC/USDT"],
    start_date: Annotated[str, "start YYYY-MM-DD"],
    end_date: Annotated[str, "end YYYY-MM-DD"],
) -> str:
    """Ticker-specific crypto news from CryptoCompare (with CoinGecko status fallback)."""
    result = get_cryptocompare_news(symbol, start_date, end_date)
    if not result.startswith("NO_DATA_AVAILABLE"):
        return result

    try:
        pair = parse_crypto_pair(symbol)
        coin_id = resolve_coin_id(pair.base)
        if coin_id:
            data = http_get_json(
                "https://api.coingecko.com/api/v3/coins/" + coin_id + "/status_updates",
                params={"per_page": 20},
            )
            updates = data.get("status_updates") or []
            lines = [f"# CoinGecko status updates for {pair.display}", ""]
            for upd in updates[:15]:
                lines.append(f"- {upd.get('description', '')[:300]}")
            if len(lines) > 2:
                return "\n".join(lines)
    except Exception as exc:
        logger.debug("CoinGecko status updates failed: %s", exc)

    return result


def get_crypto_global_news(
    curr_date: Annotated[str, "current date YYYY-MM-DD"],
    look_back_days: Annotated[Optional[int], "days to look back"] = None,
    limit: Annotated[Optional[int], "max articles"] = None,
) -> str:
    """Macro crypto news — regulation, ETF flows, L1/L2 ecosystem headlines."""
    config = get_config()
    days = look_back_days if look_back_days is not None else config.get("global_news_lookback_days", 7)
    article_limit = limit if limit is not None else config.get("global_news_article_limit", 10)
    start = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")

    queries = config.get("global_news_queries") or [
        "bitcoin ETF flows regulation",
        "ethereum L2 scaling DeFi",
        "crypto macro Fed liquidity",
        "altcoin season market structure",
        "stablecoin regulation MiCA",
    ]

    from .cryptocompare import _headers, _BASE_URL

    lines = [f"# Global crypto news ({start} to {curr_date})", ""]
    count = 0
    try:
        data = http_get_json(
            f"{_BASE_URL}/data/v2/news/",
            params={"lang": "EN"},
            headers=_headers(),
        )
        articles = data.get("Data") or []
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        keywords = " ".join(queries).lower().split()

        for art in articles:
            published = datetime.utcfromtimestamp(art.get("published_on", 0))
            if published < start_dt or published > end_dt:
                continue
            title = (art.get("title") or "").lower()
            body = (art.get("body") or "").lower()
            if keywords and not any(kw in title or kw in body for kw in keywords[:5]):
                continue
            lines.append(f"## {art.get('title', 'Untitled')}")
            lines.append(f"Source: {art.get('source', 'N/A')} | {published.strftime('%Y-%m-%d')}")
            snippet = (art.get("body") or "")[:400]
            if snippet:
                lines.append(snippet)
            lines.append("")
            count += 1
            if count >= article_limit:
                break
    except Exception as exc:
        return no_data_message("GLOBAL", f"crypto global news: {exc}")

    if count == 0:
        return no_data_message("GLOBAL", "no matching crypto macro articles")
    return "\n".join(lines)
