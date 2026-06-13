"""Plain-text activity messages for paper trading and backtest events."""

from __future__ import annotations

from typing import Sequence

from tradingagents.backtest.schemas import StrategyMetrics, WinningStrategySummary


def format_provider_line(
    provider: str,
    *,
    bars: int | None = None,
    cache_hit: bool = False,
    context: str = "OHLCV",
) -> str:
    parts = [f"[{context}]"]
    if cache_hit:
        parts.append("disk cache")
    else:
        parts.append(provider)
    if bars is not None:
        parts.append(f"({bars} bars)")
    return " ".join(parts)


def format_horizon_start(lookback: str) -> str:
    return f"Backtest horizon {lookback} — fetching history…"


def format_horizon_skipped(lookback: str, reason: str) -> str:
    return f"Backtest {lookback} skipped — {reason}"


def format_horizon_complete(
    lookback: str,
    provider: str,
    bar_count: int,
    metrics: Sequence[StrategyMetrics],
    *,
    cache_hit: bool = False,
) -> str:
    provider_part = format_provider_line(
        provider, bars=bar_count, cache_hit=cache_hit, context=lookback
    )
    if not metrics:
        return f"{provider_part} — no strategy results"
    best = max(metrics, key=lambda m: m.net_profit_ratio)
    return (
        f"{provider_part} — best: {best.strategy_name} "
        f"(net {best.net_profit_ratio:+.2%}, PF {best.profit_factor:.2f}, "
        f"{best.num_trades} trades)"
    )


def format_optimization_winner(
    winner: WinningStrategySummary,
    *,
    prefix: str = "Winner",
) -> str:
    base = (
        f"{prefix}: {winner.strategy_name} ({winner.lookback}) — "
        f"net {winner.historical_profit_ratio:+.2%}, "
        f"PF {winner.profit_factor:.2f}, Sharpe {winner.sharpe_ratio:.2f}"
    )
    if winner.train_profit_ratio is not None and winner.validate_profit_ratio is not None:
        return (
            f"{base} | walk-forward train {winner.train_profit_ratio:+.2%} / "
            f"validate {winner.validate_profit_ratio:+.2%}"
        )
    return base


def format_drawdown_rebacktest_banner(drawdown_pct: float) -> str:
    return f"══ Drawdown review ({drawdown_pct:.2f}%) — re-running backtest ══"


def format_price_feed(source: str, price: float, *, first: bool = False) -> str:
    label = "Price feed" if first else "Price source"
    return f"{label}: {source} @ ${price:,.4f}"


def format_tick_action(action: str, price: float, equity: float) -> str:
    labels = {
        "stop_loss_exit": "STOP-LOSS exit",
        "take_profit_exit": "TAKE-PROFIT exit",
        "signal_exit": "Signal exit",
        "enter_long": "Enter LONG",
        "enter_short": "Enter SHORT",
        "manual_close": "Close and retest (c)",
    }
    label = labels.get(action, action.replace("_", " ").title())
    return f"{label} @ ${price:,.4f} — equity ${equity:,.2f}"


def format_strategy_switch(old: str, new: str, *, reason: str = "drawdown review") -> str:
    return f"Strategy switch ({reason}): {old} → {new}"


def format_session_start(
    symbol: str,
    strategy: str,
    lookback: str,
    *,
    adaptive: bool,
    interval: float,
) -> str:
    mode = "adaptive on" if adaptive else "adaptive off"
    return (
        f"Paper session started — {symbol}, {strategy} ({lookback}), "
        f"{mode}, tick {interval:.0f}s"
    )
