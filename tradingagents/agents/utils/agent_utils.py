import functools
import logging
from typing import Any, Mapping, Optional

from langchain_core.messages import HumanMessage, RemoveMessage

from tradingagents.agents.utils.crypto_price_tools import get_crypto_ohlcv
from tradingagents.agents.utils.technical_indicators_tools import get_indicators
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_onchain_metrics,
    get_tokenomics,
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_global_news,
    get_sentiment,
    get_perps_data,
)
from tradingagents.agents.utils.market_data_validation_tools import (
    get_verified_market_snapshot,
)

logger = logging.getLogger(__name__)


def get_language_instruction() -> str:
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def _clean_identity_value(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"none", "n/a", "nan", "null"}:
        return None
    return cleaned


@functools.lru_cache(maxsize=256)
def resolve_instrument_identity(ticker: str) -> dict:
    """Resolve crypto asset identity via CoinGecko (cached, fail-open)."""
    try:
        from tradingagents.dataflows.coingecko import get_coin_identity
        from tradingagents.dataflows.symbol_utils import parse_crypto_pair

        pair = parse_crypto_pair(ticker)
        raw = get_coin_identity(pair)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not resolve crypto identity for %s: %s", ticker, exc)
        return {}

    identity: dict[str, str] = {}
    name = _clean_identity_value(raw.get("name"))
    if name:
        identity["name"] = name
    symbol = _clean_identity_value(raw.get("symbol"))
    if symbol:
        identity["symbol"] = symbol
    categories = _clean_identity_value(raw.get("categories"))
    if categories:
        identity["categories"] = categories
    rank = raw.get("market_cap_rank")
    if rank is not None:
        identity["market_cap_rank"] = str(rank)
    return identity


def build_instrument_context(
    ticker: str,
    asset_type: str = "crypto",
    identity: Optional[Mapping[str, str]] = None,
) -> str:
    """Describe the crypto pair so agents preserve identity across the graph."""
    context = (
        f"The crypto pair to analyze is `{ticker}`. "
        "Use this exact pair in every tool call, report, and recommendation "
        "(format: BASE/QUOTE, e.g. BTC/USDT, ETH/USDC, SOL/USD)."
    )

    details = []
    if identity:
        name = identity.get("name")
        if name:
            details.append(f"Asset: {name}")
        if identity.get("symbol"):
            details.append(f"Symbol: {identity['symbol']}")
        if identity.get("categories"):
            details.append(f"Categories: {identity['categories']}")
        if identity.get("market_cap_rank"):
            details.append(f"Market cap rank: #{identity['market_cap_rank']}")

    if details:
        context += (
            f" Resolved identity: {'; '.join(details)}. "
            "Do not substitute a different asset unless a tool result "
            "explicitly disproves this identity."
        )

    context += (
        " Crypto markets trade 24/7/365. Focus on on-chain metrics, "
        "tokenomics, perps funding/OI, and technicals — not equity fundamentals."
    )
    return context


def get_instrument_context_from_state(state: Mapping[str, Any]) -> str:
    context = state.get("instrument_context")
    if isinstance(context, str) and context.strip():
        return context
    return build_instrument_context(
        str(state["company_of_interest"]),
        state.get("asset_type", "crypto"),
    )


def create_msg_delete():
    def delete_messages(state):
        messages = state["messages"]
        removal_operations = [RemoveMessage(id=m.id) for m in messages]
        instrument_context = get_instrument_context_from_state(state)
        trade_date = state.get("trade_date", "the requested date")
        placeholder = HumanMessage(
            content=(
                f"Proceed with your assigned analysis for this workflow. "
                f"{instrument_context} The analysis date is {trade_date}."
            )
        )
        return {"messages": removal_operations + [placeholder]}

    return delete_messages
