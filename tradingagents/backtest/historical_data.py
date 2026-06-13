"""Intraday OHLCV loading for backtests — vendor chain with no sys.exit()."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Callable, Optional

import pandas as pd
import requests

from tradingagents.dataflows.symbol_utils import CryptoPair, NoMarketDataError, parse_crypto_pair

from .validation import BacktestDataError

logger = logging.getLogger(__name__)

# Candle granularity in seconds for each backtest horizon.
_GRANULARITY_5M = 300
_GRANULARITY_15M = 900
_GRANULARITY_1H = 3600

# ccxt interval string → candle length in milliseconds
_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
}


def _naive_utc_s(dt: datetime) -> int:
    """Unix seconds for a naive datetime whose wall clock is UTC (not local)."""
    ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.timestamp())


def _naive_utc_ms(dt: datetime) -> int:
    """Unix milliseconds for a naive datetime whose wall clock is UTC (not local)."""
    return _naive_utc_s(dt) * 1000

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
    to_ts = _naive_utc_s(end_dt)
    collected: list[dict] = []
    attempts = 0
    max_attempts = 5

    while to_ts > _naive_utc_s(start_dt) and attempts < max_attempts:
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
        if earliest <= _naive_utc_s(start_dt):
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
_DEFAULT_CCXT_EXCHANGES_CSV = "kraken,coinbase,binance"


def ccxt_exchange_ids(config: dict | None = None) -> tuple[str, ...]:
    """ccxt exchange order for OHLCV and live spot.

    Default: ``kraken,coinbase,binance``. Override via ``BACKTEST_CCXT_EXCHANGES`` or
    config key ``backtest_ccxt_exchanges``.
    """
    raw = os.environ.get("BACKTEST_CCXT_EXCHANGES", "").strip()
    if not raw and config is not None:
        raw = str(config.get("backtest_ccxt_exchanges", "") or "").strip()
    if not raw:
        raw = _DEFAULT_CCXT_EXCHANGES_CSV
    if raw:
        return tuple(x.strip().lower() for x in raw.split(",") if x.strip())
    return _DEFAULT_CCXT_EXCHANGES


def _ccxt_exchange_ids() -> tuple[str, ...]:
    return ccxt_exchange_ids()


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

    since_ms = _naive_utc_ms(start_dt)
    end_ms = _naive_utc_ms(end_dt)
    tf_ms = _INTERVAL_MS.get(interval, 300_000)
    rows: list = []
    seen_open: set[int] = set()
    max_pages = 64
    pages = 0
    while since_ms < end_ms and pages < max_pages:
        batch = exchange.fetch_ohlcv(market_symbol, interval, since=since_ms, limit=1000)
        pages += 1
        if not batch:
            break
        for candle in batch:
            open_ms = int(candle[0])
            if open_ms not in seen_open:
                seen_open.add(open_ms)
                rows.append(candle)
        last_open = int(batch[-1][0])
        next_since = last_open + tf_ms
        if next_since <= since_ms:
            break
        since_ms = next_since
        if last_open >= end_ms - tf_ms:
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
    df = df.drop_duplicates(subset=["Date"]).dropna(subset=["Close"]).sort_values("Date").reset_index(drop=True)
    return _slice_window(df, start_dt, end_dt)


def _fetch_ccxt_ohlcv(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    interval: str,
    config: dict | None = None,
) -> pd.DataFrame:
    pair_display = parse_crypto_pair(symbol).display
    errors: list[str] = []
    for exchange_id in ccxt_exchange_ids(config):
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


def fetch_ccxt_spot_ticker(
    symbol: str,
    exchange_id: str,
) -> tuple[float, str]:
    """Last trade price from one ccxt exchange. Returns (price, market_symbol)."""
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

    ticker = exchange.fetch_ticker(market_symbol)
    last = ticker.get("last")
    if last is None:
        raise NoMarketDataError(
            symbol,
            pair.display,
            f"{exchange_id} ticker has no last price for {market_symbol}",
        )
    price = float(last)
    if price <= 0:
        raise NoMarketDataError(
            symbol,
            pair.display,
            f"{exchange_id} returned non-positive price for {market_symbol}",
        )
    return price, market_symbol


def _skip_cryptocompare(cfg: dict | None) -> bool:
    """True when CryptoCompare should be omitted from the OHLCV vendor chain."""
    if cfg is not None and "backtest_skip_cryptocompare" in cfg:
        return bool(cfg["backtest_skip_cryptocompare"])
    raw = os.environ.get("BACKTEST_SKIP_CRYPTOCOMPARE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _build_ohlcv_vendors(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    binance_interval: str,
    cc_endpoint: str,
    resample_rule: str | None,
    config: dict | None,
) -> list[tuple[str, Callable[[], pd.DataFrame]]]:
    """Ordered OHLCV vendor chain — ccxt → Binance → CryptoCompare (optional last)."""
    cfg = config or {}
    vendors: list[tuple[str, Callable[[], pd.DataFrame]]] = []

    for exchange_id in ccxt_exchange_ids(config):
        vendors.append(
            (
                exchange_id,
                lambda ex=exchange_id: _fetch_ccxt_ohlcv_from_exchange(
                    ex, symbol, start_dt, end_dt, binance_interval
                ),
            )
        )
    vendors.append(
        (
            "Binance",
            lambda: _fetch_binance_ohlcv(symbol, start_dt, end_dt, binance_interval),
        )
    )
    if not _skip_cryptocompare(cfg):
        vendors.append(
            (
                "CryptoCompare",
                lambda: _fetch_cryptocompare_ohlcv(
                    symbol, start_dt, end_dt, cc_endpoint, resample_rule
                ),
            )
        )
    return vendors


def fetch_intraday_ohlcv(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    granularity_seconds: int,
    *,
    live_mode: bool = False,
    config: dict | None = None,
    on_provider: Optional[Callable[[str, int], None]] = None,
    on_provider_attempt: Optional[Callable[[str, int, bool, str], None]] = None,
    min_bars: int = 30,
) -> pd.DataFrame:
    """Fetch OHLCV for a backtest window via ccxt → Binance → CryptoCompare (optional).

    Tries the next vendor when a source returns too few bars or errors.
    ``on_provider_attempt(vendor, bars, ok, detail)`` fires for every try.
    """
    if granularity_seconds not in _VENDOR_SPECS:
        raise BacktestDataError(
            f"Unsupported candle granularity {granularity_seconds}s for backtest OHLCV."
        )

    binance_interval, cc_endpoint, resample_rule = _VENDOR_SPECS[granularity_seconds]
    pair_display = parse_crypto_pair(symbol).display
    errors: list[str] = []

    def _emit_attempt(vendor: str, bars: int, ok: bool, detail: str) -> None:
        if on_provider_attempt is not None:
            on_provider_attempt(vendor, bars, ok, detail)

    vendors = _build_ohlcv_vendors(
        symbol,
        start_dt,
        end_dt,
        binance_interval,
        cc_endpoint,
        resample_rule,
        config,
    )

    for name, fetcher in vendors:
        try:
            df = fetcher()
            if df is not None and not df.empty:
                bar_count = len(df)
                if bar_count >= min_bars:
                    logger.debug(
                        "Backtest OHLCV for %s via %s: %d bars",
                        pair_display,
                        name,
                        bar_count,
                    )
                    _emit_attempt(name, bar_count, True, f"{bar_count} bars")
                    if on_provider is not None:
                        on_provider(name, bar_count)
                    return df
                detail = f"only {bar_count} bars (need {min_bars})"
                errors.append(f"{name}: {detail}")
                _emit_attempt(name, bar_count, False, detail)
                continue
            detail = "empty dataframe"
            errors.append(f"{name}: {detail}")
            _emit_attempt(name, 0, False, detail)
        except NoMarketDataError as exc:
            detail = str(exc.detail or exc)
            errors.append(f"{name}: {detail}")
            _emit_attempt(name, 0, False, detail)
        except Exception as exc:
            detail = str(exc)
            errors.append(f"{name}: {detail}")
            _emit_attempt(name, 0, False, detail)

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
