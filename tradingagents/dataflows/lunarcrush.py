"""LunarCrush API — crypto social sentiment metrics."""

from __future__ import annotations

import logging
from typing import Annotated

from .crypto_common import env_api_key, http_get_json, no_data_message
from .date_window import lookback_start
from .symbol_utils import parse_crypto_pair

logger = logging.getLogger(__name__)

_BASE_URL = "https://lunarcrush.com/api4/public/coins"


def fetch_lunarcrush_sentiment(
    symbol: Annotated[str, "crypto pair or base symbol"],
    trade_date: str = "",
) -> str:
    """Fetch social sentiment metrics from LunarCrush when API key is set."""
    key = env_api_key("LUNARCRUSH_API_KEY", "TRADINGAGENTS_LUNARCRUSH_API_KEY")
    if not key:
        return (
            f"{no_data_message(symbol, 'LUNARCRUSH_API_KEY not configured')}\n"
            "Set LUNARCRUSH_API_KEY to enable LunarCrush social metrics."
        )

    try:
        pair = parse_crypto_pair(symbol)
        base = pair.base
    except ValueError:
        base = symbol.upper().split("/")[0].split("-")[0]

    try:
        data = http_get_json(
            f"{_BASE_URL}/{base.lower()}/v1",
            headers={"Authorization": f"Bearer {key}"},
        )
    except Exception as exc:
        return no_data_message(symbol, f"LunarCrush: {exc}")

    coin = data.get("data") or data
    if not coin:
        return no_data_message(symbol, "LunarCrush returned empty payload")

    lines = [
        f"# LunarCrush social metrics for {base}",
        f"Galaxy score: {coin.get('galaxy_score', 'N/A')}",
        f"Alt rank: {coin.get('alt_rank', 'N/A')}",
        f"Social volume 24h: {coin.get('social_volume_24h', 'N/A')}",
        f"Social engagement 24h: {coin.get('social_engagement_24h', 'N/A')}",
        f"Sentiment: {coin.get('sentiment', 'N/A')}",
        f"Social dominance: {coin.get('social_dominance', 'N/A')}",
    ]
    if trade_date:
        lines.insert(1, f"Analysis date: {trade_date}")
        lines.insert(2, f"Lookback window: {lookback_start(trade_date, 7)} to {trade_date} (live API snapshot)")
    return "\n".join(lines)
