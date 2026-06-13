"""Live movers panel and hotkey mapping for paper trading."""

from __future__ import annotations

from typing import Callable, Optional

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tradingagents.dataflows.market_movers import MoversSnapshot, fetch_top_movers

_MOVERS_OVERLAY_HINT = "(1–9) switch · (s) refresh · (m/esc) close"


class MoversBoard:
    """Cached Kraken (default) or optional CoinGecko gainers/losers."""

    def __init__(self, config: dict) -> None:
        self._config = dict(config)
        self._snapshot: Optional[MoversSnapshot] = None
        self._error: str = ""

    @property
    def snapshot(self) -> Optional[MoversSnapshot]:
        return self._snapshot

    def refresh(self, log_append: Optional[Callable[[str], None]] = None, *, force: bool = False) -> None:
        try:
            self._snapshot = fetch_top_movers(self._config, force_refresh=force)
            self._error = ""
            if log_append is not None:
                n_g = len(self._snapshot.gainers)
                n_l = len(self._snapshot.losers)
                log_append(
                    f"Movers updated ({self._snapshot.source}) — "
                    f"{n_g} gainers, {n_l} losers (24h)"
                )
        except Exception as exc:
            self._error = str(exc)
            if log_append is not None:
                log_append(f"Movers fetch failed — {exc}")

    def pair_for_hotkey(self, index: int) -> str | None:
        if self._snapshot is None:
            return None
        return self._snapshot.pair_for_hotkey(index)

    def render_panel(self, *, active_pair: str | None = None) -> Panel:
        title = "Kraken movers"
        if self._error:
            body = Text(f"Unavailable — {self._error}", style="dim italic")
            return Panel(body, title=title, border_style="green", expand=True)

        if self._snapshot is None:
            body = Text("Loading movers…", style="dim italic")
            return Panel(body, title=title, border_style="green", expand=True)

        table = Table(show_header=True, header_style="bold green", expand=True, pad_edge=False)
        table.add_column("#", style="dim", width=3, no_wrap=True)
        table.add_column("Pair", min_width=12, no_wrap=True)
        table.add_column("24h %", justify="right", min_width=8, no_wrap=True)
        table.add_column("Vol $M", justify="right", min_width=8, no_wrap=True)

        for idx, mover in enumerate(self._snapshot.hotkeys, start=1):
            style = "green" if mover.change_pct >= 0 else "red"
            vol_m = mover.volume_usd / 1_000_000.0
            is_active = active_pair is not None and mover.pair == active_pair
            row_style = "bold reverse green" if is_active else ""
            table.add_row(
                str(idx),
                mover.pair,
                f"[{style}]{mover.change_pct:+.1f}%[/{style}]",
                f"{vol_m:,.1f}",
                style=row_style,
            )

        footer = Text(
            f"Source: {self._snapshot.source} · {_MOVERS_OVERLAY_HINT}",
            style="dim",
        )
        return Panel(
            Group(table, footer),
            title=title,
            border_style="green",
            expand=True,
        )
