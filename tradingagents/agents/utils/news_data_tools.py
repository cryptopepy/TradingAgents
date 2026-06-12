from langchain_core.tools import tool
from typing import Annotated, Optional
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_news(
    ticker: Annotated[str, "Crypto pair e.g. BTC/USDT"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Retrieve crypto news for a trading pair or base asset."""
    return route_to_vendor("get_news", ticker, start_date, end_date)


@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[Optional[int], "Days to look back"] = None,
    limit: Annotated[Optional[int], "Max articles"] = None,
) -> str:
    """Retrieve global crypto macro news (regulation, ETF flows, ecosystem headlines)."""
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)


@tool
def get_sentiment(
    ticker: Annotated[str, "crypto pair e.g. ETH/USDT"],
    trade_date: Annotated[str, "analysis date yyyy-mm-dd"] = "",
) -> str:
    """Retrieve social sentiment metrics from LunarCrush when API key is configured."""
    return route_to_vendor("get_sentiment", ticker, trade_date)


@tool
def get_perps_data(
    ticker: Annotated[str, "crypto pair e.g. BTC/USDT"],
    curr_date: Annotated[str, "analysis date yyyy-mm-dd"] = "",
) -> str:
    """Retrieve perpetuals funding rate and open interest from Binance futures."""
    return route_to_vendor("get_perps_data", ticker, curr_date)
