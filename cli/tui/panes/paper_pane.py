"""Paper trading pane adapter for workspace sessions."""

from __future__ import annotations

from typing import Callable, Optional

from rich.console import Group

from cli.activity_log import ActivityLog
from cli.movers_board import MoversBoard
from cli.paper_display import PaperDisplayContext
from cli.price_history import PriceHistoryLog
from tradingagents.simulator.paper_engine import PaperTradingState


class PaperPane:
    """Wraps the existing paper live display and key routing."""

    pane_id = 1
    title = "Paper Trading"

    def __init__(
        self,
        *,
        render_fn: Callable[..., Group],
        handle_key_fn: Callable[[Optional[str]], Optional[str]],
        get_state: Callable[[], Optional[PaperTradingState]],
        log: ActivityLog,
        price_history: PriceHistoryLog,
        display_ctx: PaperDisplayContext,
        movers_board: MoversBoard,
    ) -> None:
        self._render_fn = render_fn
        self._handle_key_fn = handle_key_fn
        self._get_state = get_state
        self.log = log
        self.price_history = price_history
        self.display_ctx = display_ctx
        self.movers_board = movers_board

    def focus(self) -> None:
        pass

    def blur(self) -> None:
        if self.display_ctx.show_movers:
            self.display_ctx.show_movers = False
        settings = getattr(self.display_ctx, "settings", None)
        if settings is not None and getattr(settings, "is_open", False):
            settings.close()

    def render(self) -> Group:
        state = self._get_state()
        if state is None:
            from rich.panel import Panel

            return Group(Panel("Paper trading — waiting for session…", border_style="green"))
        return self._render_fn(
            state,
            self.log,
            self.price_history,
            self.display_ctx,
            self.movers_board,
        )

    def handle_key(self, event: Optional[str]) -> Optional[str]:
        return self._handle_key_fn(event)

    def tick(self) -> None:
        pass
