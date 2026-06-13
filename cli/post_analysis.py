"""Post-qualitative-analysis menu — backtest trigger and paper-trading deploy."""

from __future__ import annotations

from typing import Callable, Optional, Sequence

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from tradingagents.backtest import (
    DEFAULT_STRATEGIES,
    BacktestValidationError,
    LookbackWindow,
    OptimizationResult,
    deploy_winning_strategy,
    optimize_strategies,
    require_optimization_results,
)
from tradingagents.backtest.schemas import StrategyMetrics
from cli.paper_trading import prompt_paper_options, run_paper_session
from cli.activity_log import (
    format_optimization_winner,
    make_backtest_callbacks,
    make_progress_logger,
)

console = Console()

POST_ANALYSIS_CHOICES = [
    questionary.Choice(
        title="> Run Historical Optimization Backtest (10 strategies × 8h/24h/7d)",
        value="auto_backtest",
    ),
    questionary.Choice(
        title="> Customize Backtest Horizon & Risk Parameters",
        value="custom_backtest",
    ),
    questionary.Choice(
        title="> Deploy Optimal Strategy to Live Paper Trading Simulator",
        value="paper_trade",
    ),
    questionary.Choice(
        title="Return to Main Menu / Select New Coin Pair",
        value="main_menu",
    ),
    questionary.Choice(
        title="Exit System",
        value="exit",
    ),
]


def _aggregate_best_per_strategy(metrics: Sequence[StrategyMetrics]) -> list[StrategyMetrics]:
    """Pick the best lookback run for each strategy name."""
    best: dict[str, StrategyMetrics] = {}
    for m in metrics:
        existing = best.get(m.strategy_name)
        if existing is None or m.net_profit_ratio > existing.net_profit_ratio:
            best[m.strategy_name] = m
    return list(best.values())


def _rank_strategy_rows(
    rows: Sequence[StrategyMetrics],
    winner_name: str | None,
) -> list[StrategyMetrics]:
    """Sort by profit factor (desc), max drawdown (asc), net return (desc); winner first."""
    ranked = sorted(
        rows,
        key=lambda m: (-m.profit_factor, m.max_drawdown, -m.net_profit_ratio),
    )
    if not winner_name:
        return ranked
    winner_rows = [r for r in ranked if r.strategy_name == winner_name]
    rest = [r for r in ranked if r.strategy_name != winner_name]
    return winner_rows + rest


def render_optimization_table(optimization: OptimizationResult) -> Table:
    """Rich table: Strategy Name, Profit Factor, Max Drawdown, Net Return; mark WINNER."""
    table = Table(title=f"Backtest Results — {optimization.symbol}", show_header=True, header_style="bold cyan")
    table.add_column("Strategy", style="green")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Max Drawdown", justify="right")
    table.add_column("Net Return", justify="right")
    table.add_column("", justify="center")

    rows = _rank_strategy_rows(
        _aggregate_best_per_strategy(optimization.results),
        optimization.winner.strategy_name if optimization.winner else None,
    )
    winner_name = optimization.winner.strategy_name if optimization.winner else None

    for row in rows:
        marker = "WINNER" if row.strategy_name == winner_name else ""
        style = "bold yellow" if marker else None
        table.add_row(
            row.strategy_name,
            f"{row.profit_factor:.2f}",
            f"{row.max_drawdown:.2%}",
            f"{row.net_profit_ratio:.2%}",
            marker,
            style=style,
        )
    return table


def run_backtest_with_progress(
    ticker: str,
    analysis_date: str,
    *,
    lookbacks: Optional[Sequence[LookbackWindow]] = None,
    stop_loss_pct: float = 0.02,
    transaction_cost_pct: float = 0.001,
    strategies: Optional[Sequence] = None,
    config: Optional[dict] = None,
) -> OptimizationResult:
    """Run optimize_strategies with a Rich progress bar (zero LLM tokens)."""
    strategies = list(strategies or DEFAULT_STRATEGIES)
    lookbacks = list(lookbacks or LookbackWindow)
    total = len(strategies) * len(lookbacks)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(
            f"Backtesting {len(strategies)} strategies on {ticker}…",
            total=total,
        )
        log = make_progress_logger(progress)
        on_start, on_complete, on_skipped, on_provider_attempt = make_backtest_callbacks(log)

        def _advance(_metric: StrategyMetrics) -> None:
            progress.advance(task_id)

        result = optimize_strategies(
            ticker,
            analysis_date,
            strategies,
            stop_loss_pct=stop_loss_pct,
            transaction_cost_pct=transaction_cost_pct,
            lookbacks=lookbacks,
            on_metric=_advance,
            on_horizon_start=on_start,
            on_horizon_complete=on_complete,
            on_horizon_skipped=on_skipped,
            on_horizon_provider_attempt=on_provider_attempt,
            config=config,
        )

    result = require_optimization_results(result)
    if result.winner is not None:
        console.print()
        console.print(f"[green]{format_optimization_winner(result.winner)}[/green]")
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")

    return result


def prompt_custom_backtest_params() -> dict:
    """Interactive customization for horizon and risk parameters."""
    horizon_choice = questionary.select(
        "Select lookback horizon(s):",
        choices=[
            questionary.Choice("All (8h, 24h, 7d)", value="all"),
            questionary.Choice("8 hours", value="8h"),
            questionary.Choice("24 hours", value="24h"),
            questionary.Choice("7 days", value="7d"),
        ],
    ).ask()

    if horizon_choice == "all":
        lookbacks = list(LookbackWindow)
    else:
        lookbacks = [LookbackWindow(horizon_choice)]

    stop_loss_str = questionary.text(
        "Stop-loss % (e.g. 0.02 for 2%):",
        default="0.02",
    ).ask() or "0.02"
    stop_loss_pct = float(stop_loss_str)
    take_profit_str = questionary.text(
        "Take-profit % (empty = 2× stop-loss):",
        default="",
    ).ask() or ""
    fee_str = questionary.text(
        "Transaction cost % per side (e.g. 0.001 for 0.1%):",
        default="0.001",
    ).ask() or "0.001"

    params: dict = {
        "lookbacks": lookbacks,
        "stop_loss_pct": stop_loss_pct,
        "transaction_cost_pct": float(fee_str),
    }
    if take_profit_str.strip():
        params["take_profit_pct"] = float(take_profit_str)
    return params


def prompt_deploy_simulator(
    optimization: OptimizationResult,
    config: dict,
) -> None:
    """Optional follow-up: deploy winning strategy to full paper simulator."""
    if optimization.winner is None:
        console.print("[yellow]No winning strategy to deploy.[/yellow]")
        return

    deploy = questionary.confirm(
        "Deploy optimal strategy to the live paper trading simulator?",
        default=True,
    ).ask()
    if not deploy:
        return

    optimization = deploy_winning_strategy(optimization, config)
    opts = prompt_paper_options(config, ticker=optimization.symbol)
    run_paper_session(
        optimization.symbol,
        config,
        ticks=opts.get("ticks"),
        adaptive=opts.get("adaptive"),
        strategy_name=optimization.winner.strategy_name,
        lookback=optimization.winner.lookback,
    )


def run_interactive_backtest(
    ticker: str,
    analysis_date: str,
    config: dict,
    *,
    custom: bool = False,
) -> Optional[OptimizationResult]:
    """Execute backtest and display results table."""
    params: dict = {}
    if custom:
        params = prompt_custom_backtest_params()

    try:
        optimization = run_backtest_with_progress(
            ticker,
            analysis_date,
            lookbacks=params.get("lookbacks"),
            stop_loss_pct=params.get("stop_loss_pct", 0.02),
            transaction_cost_pct=params.get("transaction_cost_pct", 0.001),
        )
        optimization = deploy_winning_strategy(optimization, config)
        if params.get("stop_loss_pct") is not None:
            config["paper_stop_loss_pct"] = params["stop_loss_pct"]
        if params.get("take_profit_pct") is not None:
            config["paper_take_profit_pct"] = params["take_profit_pct"]
    except BacktestValidationError as exc:
        console.print(f"[red]Backtest validation error:[/red]\n{exc}")
        return None
    except Exception as exc:
        console.print(f"[red]Backtest failed: {exc}[/red]")
        return None

    console.print()
    console.print(render_optimization_table(optimization))
    if optimization.winner:
        w = optimization.winner
        console.print(
            f"\n[bold green]Winner:[/bold green] {w.strategy_name} "
            f"({w.lookback}) — net return {w.historical_profit_ratio:.2%}"
        )
    prompt_deploy_simulator(optimization, config)
    return optimization


def show_post_analysis_menu(
    ticker: str,
    analysis_date: str,
    config: dict,
    *,
    no_backtest: bool = False,
    on_main_menu: Optional[Callable[[], None]] = None,
) -> str:
    """Show post-analysis menu; returns final action ('exit' or 'main_menu')."""
    console.print()
    console.print(
        Panel(
            f"Qualitative Analysis Completed for [bold]{ticker}[/bold].\n"
            "Select Next Action:",
            title="Analysis Complete",
            border_style="cyan",
        )
    )

    choices = POST_ANALYSIS_CHOICES
    if no_backtest:
        choices = [c for c in choices if c.value in ("main_menu", "exit")]

    while True:
        action = questionary.select(
            "Select Next Action:",
            choices=choices,
            use_indicator=True,
        ).ask()

        if action is None or action == "exit":
            return "exit"
        if action == "main_menu":
            if on_main_menu:
                on_main_menu()
            return "main_menu"
        if action == "auto_backtest":
            run_interactive_backtest(ticker, analysis_date, config, custom=False)
            continue
        if action == "custom_backtest":
            run_interactive_backtest(ticker, analysis_date, config, custom=True)
            continue
        if action == "paper_trade":
            opts = prompt_paper_options(config, ticker=ticker)
            run_paper_session(
                ticker,
                config,
                ticks=opts.get("ticks"),
                adaptive=opts.get("adaptive"),
            )
            continue
