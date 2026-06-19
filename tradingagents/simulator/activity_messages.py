"""Plain-text activity messages for paper trading and backtest events."""

from __future__ import annotations

from typing import Sequence, Tuple

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


def format_provider_attempt(
    lookback: str,
    vendor: str,
    bars: int,
    ok: bool,
    detail: str,
) -> str:
    prefix = f"[{lookback}] {vendor}"
    if ok:
        return f"{prefix} ✓ {detail}"
    if bars > 0:
        return f"{prefix} ✗ {detail}"
    return f"{prefix} ✗ {detail or 'failed'}"


def format_horizon_start(lookback: str) -> str:
    return f"Backtest horizon {lookback} — fetching history…"


def format_horizon_skipped(lookback: str, reason: str) -> str:
    return f"Backtest {lookback} skipped — {reason}"


def _format_strategy_result(metric: StrategyMetrics) -> str:
    return (
        f"{metric.strategy_name} "
        f"(net {metric.net_profit_ratio:+.2%}, PF {metric.profit_factor:.2f}, "
        f"{metric.num_trades} trades)"
    )


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
    return f"{provider_part} — best: {_format_strategy_result(best)}"


def format_horizon_worst(lookback: str, metrics: Sequence[StrategyMetrics]) -> str | None:
    """Worst strategy on a horizon, or None when there is nothing useful to show."""
    if len(metrics) < 2:
        return None
    worst = min(metrics, key=lambda m: m.net_profit_ratio)
    best = max(metrics, key=lambda m: m.net_profit_ratio)
    if worst.strategy_name == best.strategy_name and worst.net_profit_ratio == best.net_profit_ratio:
        return None
    return f"[{lookback}] worst: {_format_strategy_result(worst)}"


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


def format_volatility_spike_banner(reason: str) -> str:
    return f"══ Fast-move review ({reason}) — re-checking strategy ══"


def format_spike_session_line(
    *,
    enabled: bool,
    intelligent_tuning: bool,
    windows: Sequence[Tuple[float, float]],
    cooldown_minutes: float,
) -> str:
    if not enabled:
        return "Fast-move review: off"
    window_bits = ", ".join(f"{w:g}m/{thr:.1f}%" for w, thr in windows)
    mode = "intelligent tuning on" if intelligent_tuning else "fixed thresholds"
    return (
        f"Fast-move review: on ({mode}) — watch {window_bits}; "
        f"cooldown {cooldown_minutes:.0f}m"
    )


def format_spike_tuning_update(note: str, windows: Sequence[Tuple[float, float]]) -> str:
    window_bits = ", ".join(f"{w:g}m/{thr:.1f}%" for w, thr in windows)
    return f"Fast-move thresholds updated ({note}) — {window_bits}"


def format_session_heartbeat(state) -> str:
    """Periodic status line for the activity log."""
    pos = state.open_position or "flat"
    spike = (
        f" | fast-move {state.spike_status_line}"
        if state.spike_review_enabled
        else ""
    )
    return (
        f"Status — {state.activity_status} | equity ${state.equity:,.2f} "
        f"({state.pnl_pct:+.2f}%) | DD {state.drawdown_pct:.2f}%/"
        f"{state.max_drawdown_pct:.1f}% | {pos}{spike}"
    )


def format_session_config_summary(
    *,
    stop_loss_pct: float,
    take_profit_pct: float | None,
    adaptive: bool,
    drawdown_window_minutes: float,
    max_drawdown_pct: float,
    spike_enabled: bool,
    spike_intelligent_tuning: bool,
    tick_interval_seconds: float,
) -> str:
    tp = (
        f"{take_profit_pct * 100:.1f}%"
        if take_profit_pct is not None
        else f"{stop_loss_pct * 200:.1f}% (2× SL)"
    )
    adaptive_part = (
        f"adaptive on ({drawdown_window_minutes:.0f}m / {max_drawdown_pct:.1f}% cap)"
        if adaptive
        else "adaptive off"
    )
    if spike_enabled:
        spike_mode = "intelligent" if spike_intelligent_tuning else "fixed thresholds"
        spike_part = f"fast-move on ({spike_mode})"
    else:
        spike_part = "fast-move off"
    return (
        f"Risk — SL {stop_loss_pct * 100:.1f}% / TP {tp} | "
        f"{adaptive_part} | {spike_part} | tick {tick_interval_seconds:.0f}s"
    )


def format_reanalyze_banner() -> str:
    return "══ Reanalyze (r) — re-running backtest ══"


def format_close_retest_banner() -> str:
    return "══ Close & retest (c) — re-running backtest ══"


def format_close_retest_confirm_prompt() -> str:
    return "Close position & re-run backtest? (y/n)"


def format_reanalyze_confirm_prompt() -> str:
    return "Re-run backtest without closing position? (y/n)"


def format_price_feed(
    source: str,
    price: float,
    *,
    endpoint: str | None = None,
    failures: Sequence[str] | None = None,
    first: bool = False,
) -> str:
    label = "Price feed" if first else "Price source"
    line = f"{label}: {source} @ ${price:,.4f}"
    if endpoint:
        line += f" ({endpoint})"
    if failures:
        line += f" — skipped: {'; '.join(failures)}"
    return line


def format_vendor_failures(attempts: Sequence) -> list[str]:
    """Compact failure lines from ``VendorAttempt`` tuples."""
    failures: list[str] = []
    for attempt in attempts:
        if getattr(attempt, "ok", False):
            continue
        vendor = getattr(attempt, "vendor", "unknown")
        detail = getattr(attempt, "detail", "") or "failed"
        failures.append(f"{vendor}: {detail}")
    return failures


def format_tick_action(action: str, price: float, equity: float) -> str:
    labels = {
        "stop_loss_exit": "STOP-LOSS exit",
        "take_profit_exit": "TAKE-PROFIT exit",
        "signal_exit": "Signal exit",
        "enter_long": "Enter LONG",
        "enter_short": "Enter SHORT",
        "manual_close": "Close position and retest (c)",
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
