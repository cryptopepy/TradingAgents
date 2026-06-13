"""Mathematical strategy backtesting engine (no LLM).

Fetches intraday crypto history via CryptoCompare / Binance / ccxt,
caches CSV locally, runs pure-code strategies across 8h/24h/7d horizons,
and optionally bridges the winning parameters to a live or dummy price feed.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.dummy_feed import DummyPriceFeed
from tradingagents.dataflows.symbol_utils import parse_crypto_pair

from .historical_data import fetch_intraday_ohlcv
from .matcher import SimulatedMatcher
from .portfolio import Direction, TransactionIntent, VirtualPortfolio, signals_to_intents
from .param_search import param_candidates
from .schemas import OptimizationResult, StrategyMetrics, WinningStrategySummary
from .strategies import DEFAULT_STRATEGIES, STRATEGY_REGISTRY, Strategy, build_strategy
from .validation import BacktestDataError
from .walk_forward import (
    attach_walk_forward_fields,
    split_walk_forward,
    walk_forward_deployable,
)
from .winner_gate import select_winner, winner_gate_from_config, _risk_params_from_metric

logger = logging.getLogger(__name__)

# Historic-Crypto granularity values (seconds).
_GRANULARITY_5M = 300
_GRANULARITY_15M = 900
_GRANULARITY_1H = 3600

_LOOKBACK_GRANULARITY = {
    "8h": _GRANULARITY_5M,
    "24h": _GRANULARITY_15M,
    "7d": _GRANULARITY_1H,
}

# Default OHLCV disk-cache TTL when BACKTEST_CACHE_TTL_SECONDS is unset.
_DEFAULT_CACHE_TTL_BY_GRANULARITY: dict[int, int] = {
    _GRANULARITY_5M: 600,   # 10 min for 5m bars (8h window)
    _GRANULARITY_15M: 900,  # 15 min for 15m bars (24h window)
    _GRANULARITY_1H: 3600,  # 1 h for hourly bars (7d window)
}
_HISTORIC_CACHE_TTL_SECONDS = 86400  # past (non-today) windows — data is stable

_CRYPTO_PERIODS_PER_YEAR = 365 * 24  # hourly annualization baseline


class LookbackWindow(str, Enum):
    """Supported runtime lookback windows (24/7 crypto)."""

    H8 = "8h"
    H24 = "24h"
    D7 = "7d"

    def to_timedelta(self) -> timedelta:
        if self == LookbackWindow.H8:
            return timedelta(hours=8)
        if self == LookbackWindow.H24:
            return timedelta(hours=24)
        return timedelta(days=7)

    def granularity_seconds(self) -> int:
        return _LOOKBACK_GRANULARITY[self.value]


@dataclass
class TradeRecord:
    entry_date: str
    exit_date: str
    side: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    exit_reason: str


@dataclass
class BacktestResult:
    symbol: str
    end_date: str
    lookback: LookbackWindow
    total_return_pct: float
    num_trades: int
    win_rate: float
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    net_profit_ratio: float = 0.0
    trades: List[TradeRecord] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _historic_ticker(symbol: str) -> str:
    """Map ``BTC/USDT`` → ``BTC-USD`` for Coinbase / Historic-Crypto."""
    pair = parse_crypto_pair(symbol)
    quote = pair.quote
    if quote in ("USDT", "USDC", "BUSD"):
        quote = "USD"
    return f"{pair.base}-{quote}"


def _format_historic_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d-%H-%M")


def _utc_now_naive(*, now: datetime | None = None) -> datetime:
    """Return current UTC time as a naive datetime (matches OHLCV Date columns)."""
    if now is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        return now.astimezone(timezone.utc).replace(tzinfo=None)
    return now


def _resolve_backtest_end_dt(
    end_date: str,
    *,
    now: datetime | None = None,
) -> tuple[datetime, bool]:
    """Return UTC-naive end datetime for a backtest window, capped to now when needed."""
    end_of_day = pd.to_datetime(end_date).to_pydatetime().replace(
        hour=23, minute=59, second=0, microsecond=0
    )
    now_utc = _utc_now_naive(now=now)
    end_dt = min(end_of_day, now_utc)
    capped = end_dt < end_of_day
    if capped:
        logger.debug(
            "Capped backtest end time from %s to now (%s) for analysis date %s",
            end_of_day.strftime("%Y-%m-%d %H:%M"),
            end_dt.strftime("%Y-%m-%d %H:%M"),
            end_date,
        )
    return end_dt, capped


def _last_closed_bar_dt(dt: datetime, granularity_seconds: int) -> datetime:
    """Open time of the last fully closed OHLCV bar at or before dt (naive UTC)."""
    ts = int(pd.Timestamp(dt).tz_localize("UTC").timestamp())
    current_bar_open = ts - (ts % granularity_seconds)
    last_closed_open = current_bar_open - granularity_seconds
    return (
        pd.Timestamp(last_closed_open, unit="s", tz="UTC")
        .tz_localize(None)
        .to_pydatetime()
    )


def _cache_path(ticker: str, granularity: int, start: str, end: str) -> Path:
    config = get_config()
    cache_dir = Path(config["data_cache_dir"]) / "historic_crypto"
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = ticker.replace("/", "-")
    return cache_dir / f"{safe}-g{granularity}-{start}-{end}.csv"


def _cache_ttl_seconds(
    granularity: int,
    *,
    capped: bool,
    config: dict | None = None,
) -> int:
    """TTL for historic_crypto CSV cache; shorter when the end date is capped to today."""
    cfg = config or get_config()
    override = os.environ.get("BACKTEST_CACHE_TTL_SECONDS")
    if override is None or str(override).strip() == "":
        override = cfg.get("backtest_cache_ttl_seconds")
    if override is not None and str(override).strip() != "" and int(override) > 0:
        return int(override)
    if not capped:
        return _HISTORIC_CACHE_TTL_SECONDS
    return _DEFAULT_CACHE_TTL_BY_GRANULARITY.get(granularity, 600)


def _cache_is_fresh(
    cache_file: Path,
    ttl_seconds: int,
    *,
    capped: bool,
    end_dt: datetime,
    now: datetime | None = None,
) -> bool:
    """True when a cached CSV is within TTL and safe to reuse for the requested window."""
    if not cache_file.exists():
        return False
    now_utc = _utc_now_naive(now=now)
    mtime = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc).replace(
        tzinfo=None
    )
    if capped and mtime.date() < now_utc.date():
        # End-of-day cap and last-closed-bar floor change at midnight.
        return False
    if capped and end_dt.date() == now_utc.date() and mtime.date() < end_dt.date():
        return False
    age = time.time() - cache_file.stat().st_mtime
    return age <= ttl_seconds


def _normalize_historic_df(raw: pd.DataFrame) -> pd.DataFrame:
    """Standardize Historic-Crypto output to OHLCV with Date column."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])

    df = raw.copy()
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    rename_map = {
        "time": "Date",
        "index": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    if "Date" not in df.columns:
        for col in df.columns:
            if "time" in col.lower() or "date" in col.lower():
                df = df.rename(columns={col: "Date"})
                break
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
    return df


def _cache_covers_range(
    cached: pd.DataFrame,
    start: datetime,
    end: datetime,
    *,
    min_bars: int = 30,
) -> bool:
    """True when cached rows cover the window with enough bars for a backtest."""
    if cached.empty:
        return False
    mask = (cached["Date"] >= pd.Timestamp(start)) & (cached["Date"] <= pd.Timestamp(end))
    if mask.sum() >= min_bars:
        return True
    dates = pd.to_datetime(cached["Date"])
    return dates.min() <= start and dates.max() >= end - timedelta(minutes=5)


def fetch_historical_crypto(
    symbol: str,
    end_date: str,
    lookback: LookbackWindow,
    *,
    force_refresh: bool = False,
    config: Optional[dict] = None,
    now: datetime | None = None,
    on_fetch: Optional[Callable[[str, int, bool], None]] = None,
    extra_hours: float = 0.0,
) -> pd.DataFrame:
    """Load OHLCV for a lookback window with local CSV cache and vendor fallbacks.

    ``on_fetch`` receives ``(provider_label, bar_count, cache_hit)`` when data is loaded.
    """
    ticker = _historic_ticker(symbol)
    granularity = lookback.granularity_seconds()
    end_dt, capped = _resolve_backtest_end_dt(end_date, now=now)
    if capped:
        floored = _last_closed_bar_dt(end_dt, granularity)
        if floored < end_dt:
            logger.debug(
                "Floored backtest end from %s to last closed %ss bar at %s",
                end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                granularity,
                floored.strftime("%Y-%m-%d %H:%M:%S"),
            )
            end_dt = floored
    start_dt = end_dt - lookback.to_timedelta() - timedelta(hours=extra_hours)
    if end_dt <= start_dt:
        raise BacktestDataError(
            f"Not enough history yet today for {lookback.value} window — try yesterday or wait."
        )
    start_str = _format_historic_date(start_dt)
    end_str = _format_historic_date(end_dt)
    cache_file = _cache_path(ticker, granularity, start_str, end_str)

    cfg = config or get_config()
    ttl_seconds = _cache_ttl_seconds(granularity, capped=capped, config=cfg)

    if not force_refresh and _cache_is_fresh(
        cache_file, ttl_seconds, capped=capped, end_dt=end_dt, now=now
    ):
        cached = _normalize_historic_df(pd.read_csv(cache_file))
        if _cache_covers_range(cached, start_dt, end_dt):
            logger.debug(
                "Backtest OHLCV cache hit for %s (%s → %s, ttl=%ds)",
                ticker,
                start_str,
                end_str,
                ttl_seconds,
            )
            mask = (cached["Date"] >= pd.Timestamp(start_dt)) & (
                cached["Date"] <= pd.Timestamp(end_dt)
            )
            sliced = cached.loc[mask].reset_index(drop=True)
            if on_fetch is not None:
                on_fetch("disk cache", len(sliced), True)
            return sliced
        logger.info("Cache incomplete for %s — refetching", cache_file.name)
    elif not force_refresh and cache_file.exists():
        logger.debug(
            "Backtest OHLCV cache stale for %s (ttl=%ds, capped=%s) — refetching",
            cache_file.name,
            ttl_seconds,
            capped,
        )
    fetch_provider: dict[str, str | int] = {"name": "unknown", "bars": 0}

    def _record_provider(name: str, bars: int) -> None:
        fetch_provider["name"] = name
        fetch_provider["bars"] = bars

    df = fetch_intraday_ohlcv(
        symbol,
        start_dt,
        end_dt,
        granularity,
        live_mode=is_live_mode(cfg),
        config=cfg,
        on_provider=_record_provider,
    )
    df = _normalize_historic_df(df)
    if df.empty:
        raise BacktestDataError(
            f"No OHLCV bars returned for {symbol} ({lookback.value} ending {end_date}). "
            "Try a more recent end date, check network/API keys, or pass --live for ccxt fallback."
        )
    df.to_csv(cache_file, index=False)
    if on_fetch is not None:
        on_fetch(str(fetch_provider["name"]), len(df), False)
    return df


def fetch_historical_price_slice(
    symbol: str,
    end_date: str,
    lookback_hours: int,
) -> pd.DataFrame:
    """Backward-compatible slice API used by legacy callers."""
    if lookback_hours <= 8:
        window = LookbackWindow.H8
    elif lookback_hours <= 24:
        window = LookbackWindow.H24
    else:
        window = LookbackWindow.D7
    return fetch_historical_crypto(symbol, end_date, window)


def _resolve_take_profit_pct(
    take_profit_pct: Optional[float],
    stop_loss_pct: float,
) -> float:
    if take_profit_pct is not None:
        return take_profit_pct
    return stop_loss_pct * 2.0


def _iter_risk_param_sets(
    config: dict,
    stop_loss_pct: float,
    take_profit_pct: Optional[float],
    transaction_cost_pct: float,
) -> List[tuple[float, Optional[float], float]]:
    """Yield (stop_loss, take_profit, transaction_cost) combos for optimization."""
    if not config.get("optimize_risk_params"):
        return [(stop_loss_pct, take_profit_pct, transaction_cost_pct)]

    combos: List[tuple[float, Optional[float], float]] = []
    for sl in (0.01, 0.015, 0.02):
        for tp_mult in (2.0, 3.0):
            for cost in (0.001, 0.002):
                combos.append((sl, sl * tp_mult, cost))
    max_runs = int(config.get("optimize_risk_max_runs", 500))
    return combos[:max_runs]


def _compute_drawdown(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    peak = equity_curve.cummax()
    dd = (equity_curve - peak) / peak.replace(0, np.nan)
    return float(abs(dd.min())) if dd.notna().any() else 0.0


def _compute_sharpe(returns: pd.Series, periods_per_year: float) -> float:
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def _submit_exit(
    matcher: SimulatedMatcher,
    asset: str,
    ts: datetime,
    price: float,
) -> None:
    matcher.submit_intent(
        TransactionIntent(timestamp=ts, asset=asset, direction=Direction.EXIT),
        reference_price=price,
    )


def _index_intents_by_bar(
    df: pd.DataFrame,
    intents: List[TransactionIntent],
) -> Dict[int, List[TransactionIntent]]:
    """Map each intent to the nearest OHLCV bar index."""
    indexed: Dict[int, List[TransactionIntent]] = defaultdict(list)
    dates = pd.to_datetime(df["Date"])
    for intent in intents:
        idx = int((dates - pd.Timestamp(intent.timestamp)).abs().argmin())
        indexed[idx].append(intent)
    return indexed


def _record_exit_trade(
    trades: List[TradeRecord],
    dates: List[str],
    entry_idx: int,
    exit_idx: int,
    position: int,
    entry_price: float,
    exit_price: float,
    transaction_cost_pct: float,
    exit_reason: str,
) -> None:
    move = (exit_price - entry_price) / entry_price
    if position < 0:
        move = -move
    if exit_reason == "stop_loss":
        net = move - 2 * transaction_cost_pct
    else:
        net = move - 2 * transaction_cost_pct
    trades.append(
        TradeRecord(
            entry_date=dates[entry_idx],
            exit_date=dates[exit_idx],
            side="long" if position > 0 else "short",
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=net * 100,
            exit_reason=exit_reason,
        )
    )


def run_strategy_on_frame(
    df: pd.DataFrame,
    strategy: Strategy,
    *,
    symbol: str = "ASSET",
    stop_loss_pct: float = 0.02,
    take_profit_pct: Optional[float] = None,
    transaction_cost_pct: float = 0.001,
) -> BacktestResult:
    """Simulate a strategy on a prepared OHLCV frame via VirtualPortfolio."""
    end_date = ""
    lookback = LookbackWindow.D7
    notes: List[str] = []

    if len(df) < 30:
        return BacktestResult(
            symbol=symbol,
            end_date=end_date,
            lookback=lookback,
            total_return_pct=0.0,
            num_trades=0,
            win_rate=0.0,
            notes=[f"Insufficient data ({len(df)} rows) for backtest"],
        )

    close = df["Close"].astype(float)
    signals = strategy.generate_signals(df)
    intents = signals_to_intents(df, symbol, signals)
    intent_by_bar = _index_intents_by_bar(df, intents)
    dates = df["Date"].dt.strftime("%Y-%m-%d %H:%M").tolist()

    matcher = SimulatedMatcher(
        slippage_bps=transaction_cost_pct * 10_000,
        portfolio=VirtualPortfolio(initial_equity=1.0),
    )

    position = 0
    entry_price = 0.0
    entry_idx = 0
    trades: List[TradeRecord] = []
    equity_points: List[float] = [matcher.portfolio.equity]
    bar_returns: List[float] = []
    resolved_tp = _resolve_take_profit_pct(take_profit_pct, stop_loss_pct)

    for i in range(1, len(df)):
        price = float(close.iloc[i])
        ts = pd.Timestamp(df["Date"].iloc[i]).to_pydatetime()
        prev_equity = matcher.portfolio.equity
        bar_intents = intent_by_bar.get(i, [])

        if position != 0:
            move = (price - entry_price) / entry_price
            if position < 0:
                move = -move
            if move <= -stop_loss_pct:
                _submit_exit(matcher, symbol, ts, price)
                _record_exit_trade(
                    trades,
                    dates,
                    entry_idx,
                    i,
                    position,
                    entry_price,
                    price,
                    transaction_cost_pct,
                    "stop_loss",
                )
                position = 0
                matcher.mark_to_market({symbol: price})
                bar_returns.append(
                    (matcher.portfolio.equity - prev_equity) / prev_equity if prev_equity else 0.0
                )
                equity_points.append(matcher.portfolio.equity)
                continue
            if move > 0 and move >= resolved_tp:
                _submit_exit(matcher, symbol, ts, price)
                _record_exit_trade(
                    trades,
                    dates,
                    entry_idx,
                    i,
                    position,
                    entry_price,
                    price,
                    transaction_cost_pct,
                    "take_profit",
                )
                position = 0
                matcher.mark_to_market({symbol: price})
                bar_returns.append(
                    (matcher.portfolio.equity - prev_equity) / prev_equity if prev_equity else 0.0
                )
                equity_points.append(matcher.portfolio.equity)
                continue

        for j, intent in enumerate(bar_intents):
            if intent.direction == Direction.EXIT and position != 0:
                remaining = [x.direction for x in bar_intents[j + 1 :]]
                flip = any(d in (Direction.LONG, Direction.SHORT) for d in remaining)
                _record_exit_trade(
                    trades,
                    dates,
                    entry_idx,
                    i,
                    position,
                    entry_price,
                    price,
                    transaction_cost_pct,
                    "signal_flip" if flip else "signal_exit",
                )
                position = 0
            elif intent.direction == Direction.LONG:
                position = 1
                entry_price = price
                entry_idx = i
            elif intent.direction == Direction.SHORT:
                position = -1
                entry_price = price
                entry_idx = i
            matcher.submit_intent(intent, reference_price=price)

        matcher.mark_to_market({symbol: price})
        bar_returns.append(
            (matcher.portfolio.equity - prev_equity) / prev_equity if prev_equity else 0.0
        )
        equity_points.append(matcher.portfolio.equity)

    if position != 0:
        price = float(close.iloc[-1])
        ts = pd.Timestamp(df["Date"].iloc[-1]).to_pydatetime()
        _submit_exit(matcher, symbol, ts, price)
        _record_exit_trade(
            trades,
            dates,
            entry_idx,
            len(df) - 1,
            position,
            entry_price,
            price,
            transaction_cost_pct,
            "end_of_window",
        )

    equity = matcher.portfolio.equity

    gross_profit = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
    gross_loss = abs(sum(t.pnl_pct for t in trades if t.pnl_pct < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    if profit_factor == float("inf"):
        profit_factor = 99.0

    wins = sum(1 for t in trades if t.pnl_pct > 0)
    win_rate = (wins / len(trades) * 100) if trades else 0.0
    net_profit_ratio = equity - 1.0
    sharpe = _compute_sharpe(pd.Series(bar_returns), _CRYPTO_PERIODS_PER_YEAR)
    max_dd = _compute_drawdown(pd.Series(equity_points))

    return BacktestResult(
        symbol=symbol,
        end_date=end_date,
        lookback=lookback,
        total_return_pct=net_profit_ratio * 100,
        num_trades=len(trades),
        win_rate=win_rate,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        net_profit_ratio=net_profit_ratio,
        trades=trades,
        notes=notes,
    )


def run_strategy_backtest(
    symbol: str,
    end_date: str,
    lookback: LookbackWindow = LookbackWindow.D7,
    *,
    allow_short: bool = True,
    stop_loss_pct: float = 0.02,
    transaction_cost_pct: float = 0.001,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
) -> BacktestResult:
    """Legacy RSI/MACD combo backtest — delegates to RSI mean reversion."""
    from .strategies import RsiMeanReversionStrategy

    df = fetch_historical_crypto(symbol, end_date, lookback)
    strategy = RsiMeanReversionStrategy(oversold=rsi_oversold, overbought=rsi_overbought)
    result = run_strategy_on_frame(
        df,
        strategy,
        stop_loss_pct=stop_loss_pct,
        transaction_cost_pct=transaction_cost_pct,
    )
    result.symbol = symbol
    result.end_date = end_date
    result.lookback = lookback
    if not allow_short:
        result.notes.append("allow_short=False ignored in vectorized path")
    return result


def _metric_with_risk_params(
    metric: StrategyMetrics,
    sl: float,
    tp: Optional[float],
    cost: float,
) -> StrategyMetrics:
    params = dict(metric.parameters)
    params["_stop_loss_pct"] = sl
    params["_take_profit_pct"] = tp
    params["_transaction_cost_pct"] = cost
    return metric.model_copy(update={"parameters": params})


def _evaluate_strategy_on_frame(
    strategy_name: str,
    df: pd.DataFrame,
    lookback: LookbackWindow,
    risk_sets: List[tuple[float, Optional[float], float]],
    config: dict,
) -> Optional[StrategyMetrics]:
    """Best metric for one strategy across parameter and risk combos."""
    best_metric: Optional[StrategyMetrics] = None
    for params in param_candidates(strategy_name, config):
        clean = {k: v for k, v in params.items() if not str(k).startswith("_")}
        strategy = build_strategy(strategy_name, clean)
        for sl, tp, cost in risk_sets:
            result = run_strategy_on_frame(
                df,
                strategy,
                stop_loss_pct=sl,
                take_profit_pct=tp,
                transaction_cost_pct=cost,
            )
            metric = _metric_with_risk_params(
                _metrics_from_result(strategy, lookback, result),
                sl,
                tp,
                cost,
            )
            if best_metric is None or metric.net_profit_ratio > best_metric.net_profit_ratio:
                best_metric = metric
    return best_metric


def _metrics_from_result(
    strategy: Strategy,
    lookback: LookbackWindow,
    result: BacktestResult,
) -> StrategyMetrics:
    return StrategyMetrics(
        strategy_name=strategy.name,
        lookback=lookback.value,
        parameters=strategy.parameters,
        profit_factor=result.profit_factor,
        sharpe_ratio=result.sharpe_ratio,
        max_drawdown=result.max_drawdown,
        net_profit_ratio=result.net_profit_ratio,
        num_trades=result.num_trades,
        win_rate=result.win_rate,
        notes=result.notes,
    )


def optimize_strategies(
    symbol: str,
    end_date: str,
    strategies: Optional[Sequence[Strategy]] = None,
    *,
    stop_loss_pct: float = 0.02,
    take_profit_pct: Optional[float] = None,
    transaction_cost_pct: float = 0.001,
    lookbacks: Optional[Sequence[LookbackWindow]] = None,
    on_metric: Optional[Callable[[StrategyMetrics], None]] = None,
    on_horizon_start: Optional[Callable[[LookbackWindow], None]] = None,
    on_horizon_complete: Optional[
        Callable[[LookbackWindow, str, int, bool, List[StrategyMetrics]], None]
    ] = None,
    on_horizon_skipped: Optional[Callable[[LookbackWindow, str], None]] = None,
    config: Optional[dict] = None,
) -> OptimizationResult:
    """Run all strategies across 8h, 24h, and 7d horizons; pick the winner."""
    strategies = list(strategies or DEFAULT_STRATEGIES)
    windows = list(lookbacks or LookbackWindow)
    all_metrics: List[StrategyMetrics] = []
    warnings: List[str] = []
    metric_callback: Optional[Callable[[StrategyMetrics], None]] = on_metric
    cfg = config or get_config()
    gate = winner_gate_from_config(cfg)
    risk_sets = _iter_risk_param_sets(cfg, stop_loss_pct, take_profit_pct, transaction_cost_pct)
    walk_forward_enabled = bool(cfg.get("walk_forward_enabled"))
    validate_hours = float(cfg.get("walk_forward_validate_hours", 8))

    for idx, lookback in enumerate(windows):
        if idx:
            time.sleep(0.35)
        if on_horizon_start is not None:
            on_horizon_start(lookback)
        fetch_meta = {"provider": "unknown", "bars": 0, "cache_hit": False}

        def _on_fetch(provider: str, bars: int, cache_hit: bool) -> None:
            fetch_meta["provider"] = provider
            fetch_meta["bars"] = bars
            fetch_meta["cache_hit"] = cache_hit

        try:
            df = fetch_historical_crypto(
                symbol,
                end_date,
                lookback,
                config=cfg,
                on_fetch=_on_fetch,
                extra_hours=validate_hours if walk_forward_enabled else 0.0,
            )
        except BacktestDataError as exc:
            msg = f"{lookback.value}: {exc}"
            logger.warning("%s", msg)
            warnings.append(msg)
            if on_horizon_skipped is not None:
                on_horizon_skipped(lookback, str(exc))
            continue
        except Exception as exc:
            msg = f"{lookback.value}: data fetch failed — {exc}"
            logger.warning("%s", msg, exc_info=logger.isEnabledFor(logging.DEBUG))
            warnings.append(msg)
            if on_horizon_skipped is not None:
                on_horizon_skipped(lookback, str(exc))
            continue
        if len(df) < 30:
            skip_msg = f"insufficient bars ({len(df)} < 30) for {symbol}"
            warnings.append(f"{lookback.value}: {skip_msg}")
            if on_horizon_skipped is not None:
                on_horizon_skipped(lookback, skip_msg)
            continue
        eval_df = df
        val_df: Optional[pd.DataFrame] = None
        if walk_forward_enabled:
            try:
                eval_df, val_df = split_walk_forward(
                    df,
                    validate_hours,
                    lookback.granularity_seconds(),
                )
            except ValueError as exc:
                skip_msg = f"walk-forward split failed — {exc}"
                warnings.append(f"{lookback.value}: {skip_msg}")
                if on_horizon_skipped is not None:
                    on_horizon_skipped(lookback, skip_msg)
                continue

        horizon_metrics: List[StrategyMetrics] = []
        for strategy in strategies:
            best_train = _evaluate_strategy_on_frame(
                strategy.name,
                eval_df,
                lookback,
                risk_sets,
                cfg,
            )
            if best_train is None:
                continue

            if walk_forward_enabled and val_df is not None:
                sl, tp, cost = _risk_params_from_metric(
                    best_train,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    transaction_cost_pct=transaction_cost_pct,
                )
                clean = {
                    k: v
                    for k, v in best_train.parameters.items()
                    if not str(k).startswith("_")
                }
                val_strategy = build_strategy(strategy.name, clean)
                val_result = run_strategy_on_frame(
                    val_df,
                    val_strategy,
                    stop_loss_pct=sl,
                    take_profit_pct=tp,
                    transaction_cost_pct=cost,
                )
                val_metric = _metric_with_risk_params(
                    _metrics_from_result(val_strategy, lookback, val_result),
                    sl,
                    tp,
                    cost,
                )
                wf_ok, wf_fail = walk_forward_deployable(best_train, val_metric, gate)
                if not wf_ok:
                    warnings.append(
                        f"{strategy.name}/{lookback.value} walk-forward rejected: "
                        + "; ".join(wf_fail)
                    )
                    continue
                best_metric = attach_walk_forward_fields(
                    best_train,
                    train_metric=best_train,
                    validate_metric=val_metric,
                )
            else:
                best_metric = best_train

            all_metrics.append(best_metric)
            horizon_metrics.append(best_metric)
            if metric_callback is not None:
                metric_callback(best_metric)
        if on_horizon_complete is not None:
            on_horizon_complete(
                lookback,
                fetch_meta["provider"],
                fetch_meta["bars"] or len(df),
                fetch_meta["cache_hit"],
                horizon_metrics,
            )

    winner_summary: Optional[WinningStrategySummary] = None
    gate_failures: List[str] = []
    if all_metrics:
        winner_summary, gate_failures = select_winner(
            all_metrics,
            gate,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            transaction_cost_pct=transaction_cost_pct,
        )
        if winner_summary is None and gate_failures:
            warnings.append(
                "No deployable winner — " + "; ".join(gate_failures)
            )

    if not all_metrics and not warnings:
        warnings.append(
            f"No lookback windows were evaluated for {symbol} on {end_date}."
        )

    return OptimizationResult(
        symbol=symbol,
        end_date=end_date,
        results=all_metrics,
        winner=winner_summary,
        deployable=winner_summary is not None and winner_summary.deployable,
        gate_failures=gate_failures,
        warnings=warnings,
    )


def is_live_mode(config: Optional[dict] = None) -> bool:
    """True when LIVE_MODE env or config live_mode is enabled."""
    cfg = config or get_config()
    env_flag = os.environ.get("LIVE_MODE", "").strip().lower() in ("1", "true", "yes", "on")
    return bool(cfg.get("live_mode")) or env_flag


def fetch_live_price(symbol: str, config: Optional[dict] = None) -> float:
    """Fetch current price via live vendor chain (CryptoCompare → CoinGecko → Binance → placeholder)."""
    from tradingagents.dataflows.live_prices import fetch_live_spot_price_value

    quote = fetch_live_spot_price_value(symbol, config)
    logger.debug("Live price for %s: %.6f", symbol, quote)
    return quote


def compute_strategy_signal(
    symbol: str,
    strategy_name: str,
    parameters: Dict[str, Any],
    lookback: LookbackWindow | str,
    end_date: Optional[str] = None,
    config: Optional[dict] = None,
) -> str:
    """Return ``long``, ``short``, or ``flat`` for the latest bar of ``strategy_name``."""
    if strategy_name not in STRATEGY_REGISTRY:
        return "flat"
    lb = lookback if isinstance(lookback, LookbackWindow) else LookbackWindow(str(lookback))
    end = end_date or datetime.now().strftime("%Y-%m-%d")
    df = fetch_historical_crypto(symbol, end, lb, config=config)
    if df.empty:
        return "flat"
    strategy = build_strategy(strategy_name, parameters)
    signals = strategy.generate_signals(df)
    last = int(signals.iloc[-1]) if len(signals) else 0
    return {1: "long", -1: "short", 0: "flat"}.get(last, "flat")


def deploy_winning_strategy(
    optimization: OptimizationResult,
    config: Optional[dict] = None,
) -> OptimizationResult:
    """Attach live/dummy price and a paper-trading signal for the winner."""
    if optimization.winner is None:
        return optimization

    cfg = config or get_config()
    price = fetch_live_price(optimization.symbol, cfg)
    lookback = LookbackWindow(optimization.winner.lookback)
    try:
        paper_signal = compute_strategy_signal(
            optimization.symbol,
            optimization.winner.strategy_name,
            optimization.winner.parameters,
            lookback,
            optimization.end_date,
        )
    except BacktestDataError as exc:
        logger.warning("Paper signal skipped — %s", exc)
        paper_signal = "flat"

    return optimization.model_copy(
        update={"live_price": price, "paper_signal": paper_signal}
    )


def format_optimization_summary(optimization: OptimizationResult) -> str:
    """Human-readable summary for CLI / message buffer."""
    lines = [
        f"## Backtest Optimization — {optimization.symbol}",
        f"End date: {optimization.end_date}",
        f"Runs evaluated: {len(optimization.results)}",
    ]
    if optimization.winner:
        w = optimization.winner
        deploy_label = "deployable" if optimization.deployable else "not deployable"
        lines.extend(
            [
                "",
                f"### Winning Strategy ({deploy_label})",
                f"- **Name:** {w.strategy_name}",
                f"- **Lookback:** {w.lookback}",
                f"- **Historical profit ratio:** {w.historical_profit_ratio:.4f}",
                f"- **Profit factor:** {w.profit_factor:.2f}",
                f"- **Sharpe:** {w.sharpe_ratio:.2f}",
                f"- **Max drawdown:** {w.max_drawdown:.2%}",
                f"- **Trades:** {w.num_trades}",
                f"- **Risk:** SL={w.stop_loss_pct:.3f} TP={w.take_profit_pct} cost={w.transaction_cost_pct:.4f}",
                f"- **Parameters:** {w.parameters}",
            ]
        )
    elif optimization.gate_failures:
        lines.extend(["", "### No deployable winner", *[f"- {f}" for f in optimization.gate_failures]])
    if optimization.live_price is not None:
        lines.append(f"- **Current price:** {optimization.live_price:.4f}")
    if optimization.paper_signal:
        lines.append(f"- **Paper signal:** {optimization.paper_signal}")
    return "\n".join(lines)
