"""Intraday OHLCV loading for backtests — vendor chain with no sys.exit()."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Callable, Optional, Sequence

import pandas as pd
import requests

from tradingagents.dataflows.symbol_utils import CryptoPair, NoMarketDataError, parse_crypto_pair

from .validation import BacktestDataError

logger = logging.getLogger(__name__)

# Candle granularity in seconds for each backtest horizon.
_GRANULARITY_5M = 300
_GRANULARITY_15M = 900
_GRANULARITY_1H = 3600

_VENDOR_SPECS: dict[int, tuple[str, str, str | None]] = {
    _GRANULARITY_5M: ("5m", "histominute", "5min"),
    _GRANULARITY_15M: ("15m", "histominute", "15min"),
    _GRANULARITY_1H: ("1h", "histohour", None),
}


def _quote_symbol(symbol: str) -> tuple[str, str]:
    pair = parse_crypto_pair(symbol)
    tsym = pair.quote if pair.quote not in ("USDT", "USDC", "BUSD") else "USD"
    return pair.base, tsym


def _slice_window(df: pd.DataFrame, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (df["Date"] >= pd.Timestamp(start_dt)) & (df["Date"] <= pd.Timestamp(end_dt))
    return df.loc[mask].reset_index(drop=True)


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df
    indexed = df.set_index("Date")
    out = indexed.resample(rule).agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    )
    return out.dropna(subset=["Close"]).reset_index()


def _fetch_binance_ohlcv(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    interval: str,
) -> pd.DataFrame:
    from tradingagents.dataflows.binance import fetch_klines

    df = fetch_klines(
        symbol,
        start_dt.strftime("%Y-%m-%d"),
        end_dt.strftime("%Y-%m-%d"),
        interval=interval,
    )
    return _slice_window(df, start_dt, end_dt)


def _fetch_cryptocompare_ohlcv(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    endpoint: str,
    resample_rule: str | None,
) -> pd.DataFrame:
    from tradingagents.dataflows.cryptocompare import _BASE_URL, _headers
    from tradingagents.dataflows.crypto_common import http_get_json

    fsym, tsym = _quote_symbol(symbol)
    step_seconds = 60 if endpoint == "histominute" else 3600
    bars_needed = max(1, int((end_dt - start_dt).total_seconds() / step_seconds) + 5)
    to_ts = int(end_dt.timestamp())
    collected: list[dict] = []
    attempts = 0
    max_attempts = 5

    while to_ts > int(start_dt.timestamp()) and attempts < max_attempts:
        attempts += 1
        limit = min(2000, max(bars_needed - len(collected), 30))
        last_exc: Exception | None = None
        data = None
        for retry in range(4):
            try:
                data = http_get_json(
                    f"{_BASE_URL}/data/v2/{endpoint}",
                    params={"fsym": fsym, "tsym": tsym, "limit": limit, "toTs": to_ts},
                    headers=_headers(),
                )
                break
            except requests.HTTPError as exc:
                last_exc = exc
                if exc.response is not None and exc.response.status_code in (429, 503):
                    time.sleep(2 ** retry)
                    continue
                raise NoMarketDataError(
                    symbol, parse_crypto_pair(symbol).display, str(exc)
                ) from exc
            except Exception as exc:
                last_exc = exc
                time.sleep(2 ** retry)
        if data is None:
            raise NoMarketDataError(
                symbol, parse_crypto_pair(symbol).display, str(last_exc)
            ) from last_exc

        if data.get("Response") == "Error":
            raise NoMarketDataError(
                symbol,
                parse_crypto_pair(symbol).display,
                data.get("Message") or "CryptoCompare API error",
            )

        raw = (data.get("Data") or {}).get("Data") or []
        if not raw:
            break
        collected = raw + collected
        earliest = min(row["time"] for row in collected)
        if earliest <= int(start_dt.timestamp()):
            break
        to_ts = earliest - 1
        bars_needed = max(bars_needed, int((end_dt - start_dt).total_seconds() / step_seconds) + 5)
        time.sleep(0.25)

    if not collected:
        raise NoMarketDataError(
            symbol,
            parse_crypto_pair(symbol).display,
            f"CryptoCompare {endpoint} returned no rows for {start_dt}–{end_dt}",
        )

    df = pd.DataFrame(collected)
    df["Date"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_localize(None)
    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volumeto": "Volume",
        }
    )
    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    df = df.drop_duplicates(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    if resample_rule:
        df = _resample_ohlcv(df, resample_rule)
    return _slice_window(df, start_dt, end_dt)


_DEFAULT_CCXT_EXCHANGES = ("kraken", "coinbase", "binance")


def _ccxt_exchange_ids() -> tuple[str, ...]:
    raw = os.environ.get("BACKTEST_CCXT_EXCHANGES", "").strip()
    if raw:
        return tuple(x.strip().lower() for x in raw.split(",") if x.strip())
    return _DEFAULT_CCXT_EXCHANGES


def _ccxt_market_symbol(exchange, pair: CryptoPair) -> str | None:
    """Resolve a ccxt unified symbol for an exchange (e.g. BTC/USD on Coinbase)."""
    candidates: list[str] = []
    if pair.quote in ("USDT", "USDC", "BUSD"):
        # USD pairs usually have deeper intraday history on Kraken/Coinbase.
        candidates.append(f"{pair.base}/USD")
    candidates.append(pair.display)
    if pair.quote == "USD":
        candidates.append(f"{pair.base}/USDT")
    seen: set[str] = set()
    for sym in candidates:
        if sym in seen:
            continue
        seen.add(sym)
        if sym in exchange.markets:
            return sym
    return None


def _fetch_ccxt_ohlcv_from_exchange(
    exchange_id: str,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    interval: str,
) -> pd.DataFrame:
    try:
        import ccxt
    except ImportError as exc:
        raise NoMarketDataError(
            symbol,
            parse_crypto_pair(symbol).display,
            "ccxt not installed (pip install ccxt)",
        ) from exc

    pair = parse_crypto_pair(symbol)
    if not hasattr(ccxt, exchange_id):
        raise NoMarketDataError(
            symbol,
            pair.display,
            f"unknown ccxt exchange {exchange_id!r}",
        )

    exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    exchange.load_markets()
    market_symbol = _ccxt_market_symbol(exchange, pair)
    if not market_symbol:
        raise NoMarketDataError(
            symbol,
            pair.display,
            f"{exchange_id} has no market for {pair.display}",
        )

    since_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    rows: list = []
    while since_ms < end_ms:
        batch = exchange.fetch_ohlcv(market_symbol, interval, since=since_ms, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        last_open = int(batch[-1][0])
        since_ms = last_open + 1
        if len(batch) < 1000 or last_open >= end_ms:
            break

    if not rows:
        raise NoMarketDataError(
            symbol,
            pair.display,
            f"ccxt {exchange_id} returned no {interval} candles",
        )

    df = pd.DataFrame(
        rows,
        columns=["open_time", "Open", "High", "Low", "Close", "Volume"],
    )
    df["Date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_localize(None)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Close"]).sort_values("Date").reset_index(drop=True)
    return _slice_window(df, start_dt, end_dt)


def _fetch_ccxt_ohlcv(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    interval: str,
) -> pd.DataFrame:
    pair_display = parse_crypto_pair(symbol).display
    errors: list[str] = []
    for exchange_id in _ccxt_exchange_ids():
        try:
            return _fetch_ccxt_ohlcv_from_exchange(
                exchange_id, symbol, start_dt, end_dt, interval
            )
        except NoMarketDataError as exc:
            errors.append(f"{exchange_id}: {exc.detail or exc}")
        except Exception as exc:
            errors.append(f"{exchange_id}: {exc}")
    detail = "; ".join(errors) or "no ccxt exchange returned candles"
    raise NoMarketDataError(symbol, pair_display, detail)


def fetch_intraday_ohlcv(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    granularity_seconds: int,
    *,
    live_mode: bool = False,
    config: dict | None = None,
    on_provider: Optional[Callable[[str, int], None]] = None,
) -> pd.DataFrame:
    """Fetch OHLCV for a backtest window via CryptoCompare → Binance → ccxt."""
    if granularity_seconds not in _VENDOR_SPECS:
        raise BacktestDataError(
            f"Unsupported candle granularity {granularity_seconds}s for backtest OHLCV."
        )

    binance_interval, cc_endpoint, resample_rule = _VENDOR_SPECS[granularity_seconds]
    pair_display = parse_crypto_pair(symbol).display
    errors: list[str] = []
    ccxt_label = "ccxt (" + ", ".join(_ccxt_exchange_ids()) + ")"

    vendors: Sequence[tuple[str, Callable[[], pd.DataFrame]]] = [
        (
            "CryptoCompare",
            lambda: _fetch_cryptocompare_ohlcv(
                symbol, start_dt, end_dt, cc_endpoint, resample_rule
            ),
        ),
        (
            "Binance",
            lambda: _fetch_binance_ohlcv(symbol, start_dt, end_dt, binance_interval),
        ),
        (
            ccxt_label,
            lambda: _fetch_ccxt_ohlcv(symbol, start_dt, end_dt, binance_interval),
        ),
    ]
    cfg = config or {}
    if cfg.get("backtest_prefer_binance") or os.environ.get("BACKTEST_PREFER_BINANCE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        vendors = [
            (
                "Binance",
                lambda: _fetch_binance_ohlcv(symbol, start_dt, end_dt, binance_interval),
            ),
            (
                ccxt_label,
                lambda: _fetch_ccxt_ohlcv(symbol, start_dt, end_dt, binance_interval),
            ),
            (
                "CryptoCompare",
                lambda: _fetch_cryptocompare_ohlcv(
                    symbol, start_dt, end_dt, cc_endpoint, resample_rule
                ),
            ),
        ]

    for name, fetcher in vendors:
        try:
            df = fetcher()
            if df is not None and not df.empty:
                logger.debug(
                    "Backtest OHLCV for %s via %s: %d bars",
                    pair_display,
                    name,
                    len(df),
                )
                if on_provider is not None:
                    on_provider(name, len(df))
                return df
            errors.append(f"{name}: empty dataframe")
        except NoMarketDataError as exc:
            errors.append(f"{name}: {exc.detail or exc}")
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    hints = [
        "Check network connectivity and API keys (CRYPTOCOMPARE_API_KEY).",
        "Try a more recent end date or a liquid pair (e.g. BTC/USDT).",
        "ccxt fallbacks try Kraken/Coinbase/Binance — set BACKTEST_CCXT_EXCHANGES to reorder.",
        "If Binance returns HTTP 451, disable VPN or use exchanges allowed in your region.",
        "If the analysis date is today, end time is capped to now — use yesterday or wait for more history.",
    ]
    raise BacktestDataError(
        "\n".join(
            [
                f"Could not load intraday OHLCV for {pair_display} "
                f"({start_dt.strftime('%Y-%m-%d %H:%M')} → {end_dt.strftime('%Y-%m-%d %H:%M')}).",
                "",
                "Vendor errors:",
                *[f"  • {e}" for e in errors],
                "",
                "Suggestions:",
                *[f"  • {h}" for h in hints],
            ]
        )
    )
