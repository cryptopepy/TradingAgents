"""Perpetuals market data — funding rates, open interest (Binance futures public API)."""

from __future__ import annotations

import logging
from typing import Annotated

from .crypto_common import http_get_json, no_data_message
from .symbol_utils import parse_crypto_pair

logger = logging.getLogger(__name__)

_FUTURES_URL = "https://fapi.binance.com/fapi/v1"


def get_perps_snapshot(
    symbol: Annotated[str, "crypto pair e.g. BTC/USDT"],
    curr_date: Annotated[str, "analysis date YYYY-MM-DD"] = "",
) -> str:
    """Funding rate and open interest from Binance USD-M futures."""
    try:
        pair = parse_crypto_pair(symbol)
    except ValueError as exc:
        return no_data_message(symbol, str(exc))

    binance_sym = pair.binance_symbol
    lines = [
        f"# Perpetuals snapshot for {pair.display} (Binance USD-M: {binance_sym})",
    ]
    if curr_date:
        lines.append(f"Analysis date: {curr_date}")
    lines.append("")

    try:
        premium = http_get_json(
            f"{_FUTURES_URL}/premiumIndex",
            params={"symbol": binance_sym},
        )
        lines.extend([
            "## Funding / mark price",
            f"Mark price: {premium.get('markPrice', 'N/A')}",
            f"Index price: {premium.get('indexPrice', 'N/A')}",
            f"Last funding rate: {premium.get('lastFundingRate', 'N/A')}",
            f"Next funding time: {premium.get('nextFundingTime', 'N/A')}",
            "",
        ])
    except Exception as exc:
        lines.append(f"Funding data unavailable: {exc}")

    try:
        oi = http_get_json(
            f"{_FUTURES_URL}/openInterest",
            params={"symbol": binance_sym},
        )
        lines.extend([
            "## Open interest",
            f"Open interest (contracts): {oi.get('openInterest', 'N/A')}",
            "",
        ])
    except Exception as exc:
        lines.append(f"Open interest unavailable: {exc}")

    lines.append(
        "Note: Liquidations and order-book depth require authenticated feeds or "
        "dedicated market-data providers; not available on the public REST path."
    )
    return "\n".join(lines)
