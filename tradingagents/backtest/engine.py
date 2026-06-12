"""Mathematical strategy backtesting engine (no LLM).

Fetches intraday crypto history via Historic-Crypto (Coinbase candles),
caches CSV locally, runs pure-code strategies across 8h/24h/7d horizons,
and optionally bridges the winning parameters to a live or dummy price feed.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.dummy_feed import DummyPriceFeed
from tradingagents.dataflows.symbol_utils import parse_crypto_pair

from .matcher import SimulatedMatcher
from .portfolio import Direction, TransactionIntent, VirtualPortfolio, signals_to_intents
from .schemas import OptimizationResult, StrategyMetrics, WinningStrategySummary
from .strategies import DEFAULT_STRATEGIES, STRATEGY_REGISTRY, Strategy, build_strategy

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


def _cache_path(ticker: str, granularity: int, start: str, end: str) -> Path:
    config = get_config()
    cache_dir = Path(config["data_cache_dir"]) / "historic_crypto"
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = ticker.replace("/", "-")
    return cache_dir / f"{safe}-g{granularity}-{start}-{end}.csv"


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


def _cache_covers_range(cached: pd.DataFrame, start: datetime, end: datetime) -> bool:
    if cached.empty:
        return False
    dates = pd.to_datetime(cached["Date"])
    return dates.min() <= start and dates.max() >= end - timedelta(minutes=5)


def fetch_historical_crypto(
    symbol: str,
    end_date: str,
    lookback: LookbackWindow,
    *,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Load OHLCV via Historic-Crypto with local CSV cache."""
    ticker = _historic_ticker(symbol)
    granularity = lookback.granularity_seconds()
    end_dt = pd.to_datetime(end_date).to_pydatetime().replace(
        hour=23, minute=59, second=0, microsecond=0
    )
    start_dt = end_dt - lookback.to_timedelta()
    start_str = _format_historic_date(start_dt)
    end_str = _format_historic_date(end_dt)
    cache_file = _cache_path(ticker, granularity, start_str, end_str)

    if not force_refresh and cache_file.exists():
        cached = _normalize_historic_df(pd.read_csv(cache_file))
        if _cache_covers_range(cached, start_dt, end_dt):
            mask = (cached["Date"] >= pd.Timestamp(start_dt)) & (
                cached["Date"] <= pd.Timestamp(end_dt)
            )
            return cached.loc[mask].reset_index(drop=True)
        logger.info("Cache incomplete for %s — refetching", cache_file.name)

    try:
        from Historic_Crypto import HistoricalData
    except ImportError as exc:
        raise ImportError(
            "Historic-Crypto is required for intraday backtests. "
            "Install with: pip install Historic-Crypto"
        ) from exc

    raw = HistoricalData(
        ticker,
        granularity,
        start_str,
        end_str,
        verbose=False,
    ).retrieve_data()
    df = _normalize_historic_df(raw)
    if not df.empty:
        df.to_csv(cache_file, index=False)
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
    transaction_cost_pct: float = 0.001,
) -> OptimizationResult:
    """Run all strategies across 8h, 24h, and 7d horizons; pick the winner."""
    strategies = list(strategies or DEFAULT_STRATEGIES)
    all_metrics: List[StrategyMetrics] = []

    for lookback in LookbackWindow:
        try:
            df = fetch_historical_crypto(symbol, end_date, lookback)
        except Exception as exc:
            logger.warning("Historic fetch failed for %s %s: %s", symbol, lookback.value, exc)
            continue
        if len(df) < 30:
            continue
        for strategy in strategies:
            result = run_strategy_on_frame(
                df,
                strategy,
                stop_loss_pct=stop_loss_pct,
                transaction_cost_pct=transaction_cost_pct,
            )
            all_metrics.append(_metrics_from_result(strategy, lookback, result))

    winner_summary: Optional[WinningStrategySummary] = None
    if all_metrics:
        best = max(all_metrics, key=lambda m: m.net_profit_ratio)
        winner_summary = WinningStrategySummary(
            strategy_name=best.strategy_name,
            lookback=best.lookback,
            historical_profit_ratio=best.net_profit_ratio,
            parameters=best.parameters,
            profit_factor=best.profit_factor,
            sharpe_ratio=best.sharpe_ratio,
            max_drawdown=best.max_drawdown,
            num_trades=best.num_trades,
        )

    return OptimizationResult(
        symbol=symbol,
        end_date=end_date,
        results=all_metrics,
        winner=winner_summary,
    )


def is_live_mode(config: Optional[dict] = None) -> bool:
    """True when LIVE_MODE env or config live_mode is enabled."""
    cfg = config or get_config()
    env_flag = os.environ.get("LIVE_MODE", "").strip().lower() in ("1", "true", "yes", "on")
    return bool(cfg.get("live_mode")) or env_flag


def fetch_live_price(symbol: str, config: Optional[dict] = None) -> float:
    """Fetch current price via ccxt (live) or dummy feed (paper)."""
    cfg = config or get_config()
    if is_live_mode(cfg):
        try:
            import ccxt

            pair = parse_crypto_pair(symbol)
            exchange = ccxt.binance({"enableRateLimit": True})
            ticker = exchange.fetch_ticker(pair.binance_symbol)
            return float(ticker["last"])
        except Exception as exc:
            logger.warning("Live ccxt fetch failed for %s: %s — falling back to dummy", symbol, exc)

    from datetime import timezone

    df = fetch_historical_crypto(
        symbol,
        datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        LookbackWindow.H24,
    )
    anchor = float(df["Close"].iloc[-1]) if not df.empty else 1.0
    feed = DummyPriceFeed(anchor_price=anchor, symbol=symbol)
    return float(feed.fetch_ticker()["last"])


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
    df = fetch_historical_crypto(optimization.symbol, optimization.end_date, lookback)

    paper_signal = "flat"
    if not df.empty and optimization.winner.strategy_name in STRATEGY_REGISTRY:
        strategy = build_strategy(
            optimization.winner.strategy_name,
            optimization.winner.parameters,
        )
        signals = strategy.generate_signals(df)
        last = int(signals.iloc[-1]) if len(signals) else 0
        paper_signal = {1: "long", -1: "short", 0: "flat"}.get(last, "flat")

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
        lines.extend(
            [
                "",
                "### Winning Strategy",
                f"- **Name:** {w.strategy_name}",
                f"- **Lookback:** {w.lookback}",
                f"- **Historical profit ratio:** {w.historical_profit_ratio:.4f}",
                f"- **Profit factor:** {w.profit_factor:.2f}",
                f"- **Sharpe:** {w.sharpe_ratio:.2f}",
                f"- **Max drawdown:** {w.max_drawdown:.2%}",
                f"- **Parameters:** {w.parameters}",
            ]
        )
    if optimization.live_price is not None:
        lines.append(f"- **Current price:** {optimization.live_price:.4f}")
    if optimization.paper_signal:
        lines.append(f"- **Paper signal:** {optimization.paper_signal}")
    return "\n".join(lines)
