from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_crypto_ohlcv(
    symbol: Annotated[str, "crypto pair e.g. BTC/USDT, ETH/USDC"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve crypto OHLCV candle data for a trading pair.
    Uses the configured core_crypto_apis vendor (Binance primary, CryptoCompare fallback).
    Args:
        symbol: Crypto pair such as BTC/USDT, ETH/USDC, SOL/USD
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format
    Returns:
        CSV string with Open, High, Low, Close, Volume columns.
    """
    return route_to_vendor("get_crypto_ohlcv", symbol, start_date, end_date)
