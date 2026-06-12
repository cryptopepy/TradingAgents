"""Binance public API — historical OHLCV candles."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

import pandas as pd

from .crypto_common import http_get_json
from .symbol_utils import NoMarketDataError, parse_crypto_pair

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.binance.com/api/v3/klines"

_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def _to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_klines(
    symbol: str,
    start_date: str,
    end_date: str,
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV candles from Binance for a crypto pair."""
    pair = parse_crypto_pair(symbol)
    binance_sym = pair.binance_symbol
    start_ms = _to_ms(start_date)
    end_ms = _to_ms(end_date) + 86_400_000  # include end day

    rows: list = []
    cursor = start_ms
    step = _INTERVAL_MS.get(interval, 86_400_000)

    while cursor < end_ms:
        try:
            batch = http_get_json(
                _BASE_URL,
                params={
                    "symbol": binance_sym,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
        except Exception as exc:
            if not rows:
                raise NoMarketDataError(
                    symbol, pair.display, f"Binance klines failed: {exc}"
                ) from exc
            break

        if not batch:
            break
        rows.extend(batch)
        last_open = int(batch[-1][0])
        cursor = last_open + step
        if len(batch) < 1000:
            break

    if not rows:
        raise NoMarketDataError(symbol, pair.display, "Binance returned no candles")

    df = pd.DataFrame(
        rows,
        columns=[
            "open_time", "Open", "High", "Low", "Close", "Volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ],
    )
    df["Date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_localize(None)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Close"]).sort_values("Date")
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]]


def get_binance_ohlcv_csv(
    symbol: Annotated[str, "crypto pair e.g. BTC/USDT"],
    start_date: Annotated[str, "start YYYY-MM-DD"],
    end_date: Annotated[str, "end YYYY-MM-DD"],
) -> str:
    """Return OHLCV as CSV string with header."""
    df = fetch_klines(symbol, start_date, end_date)
    pair = parse_crypto_pair(symbol)
    header = (
        f"# Crypto OHLCV for {pair.display} (Binance: {pair.binance_symbol})\n"
        f"# Range: {start_date} to {end_date}\n"
        f"# Records: {len(df)}\n"
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + df.to_csv(index=False)
