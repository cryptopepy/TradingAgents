from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_fundamentals(
    ticker: Annotated[str, "crypto pair e.g. BTC/USDT"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    Retrieve comprehensive crypto fundamentals: market cap, FDV, supply, community/dev metrics.
    Uses CoinGecko via the configured fundamental_data vendor.
    """
    return route_to_vendor("get_fundamentals", ticker, curr_date)


@tool
def get_onchain_metrics(
    ticker: Annotated[str, "crypto pair e.g. ETH/USDC"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    Retrieve on-chain metrics: TVL, gas/burn notes, active-address proxies when available.
    """
    return route_to_vendor("get_onchain_metrics", ticker, curr_date)


@tool
def get_tokenomics(
    ticker: Annotated[str, "crypto pair e.g. SOL/USDT"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = "",
) -> str:
    """
    Retrieve token supply, FDV, and emission-related tokenomics.
    """
    return route_to_vendor("get_tokenomics", ticker, curr_date)
