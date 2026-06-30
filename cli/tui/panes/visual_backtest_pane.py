"""Visual backtest workspace pane."""

from __future__ import annotations

from typing import Callable, Optional

from rich.console import Group

from cli.activity_log import ActivityLog
from cli.keyboard_input import SCROLL_BOTTOM, SCROLL_DOWN, SCROLL_UP
from cli.tui.visual_backtest.display import (
    VisualBacktestDisplayContext,
    render_visual_backtest_display,
)
from cli.tui.visual_backtest.runner import VisualBacktestRunner
from cli.tui.visual_backtest.setup import VisualBacktestParams


class VisualBacktestPane:
    pane_id = 2
    title = "Visual Backtest"

    def __init__(
        self,
        config: dict,
        log: ActivityLog,
        *,
        run_setup: Callable[[], Optional[VisualBacktestParams]],
        on_refresh: Callable[[], None],
        poll_key: Callable[[float], Optional[str]],
    ) -> None:
        self.config = config
        self.log = log
        self._run_setup = run_setup
        self._on_refresh = on_refresh
        self._poll_key = poll_key
        self.display_ctx = VisualBacktestDisplayContext()
        self._runner: Optional[VisualBacktestRunner] = None
        self._setup_pending = False

    def focus(self) -> None:
        if self.display_ctx.params is None and self.display_ctx.state == "idle":
            self.display_ctx.status_message = (
                "Press Enter to configure visual backtest"
            )

    def blur(self) -> None:
        pass

    def render(self) -> Group:
        return render_visual_backtest_display(self.display_ctx, self.log)

    def _start_runner(self, params: VisualBacktestParams) -> None:
        if self._runner is not None:
            self._runner.stop()
        self.display_ctx.params = params
        self.display_ctx.state = "fetching"
        self.display_ctx.error_message = None
        self.display_ctx.summary_rows.clear()
        self.display_ctx.current_result = None
        self.log.append(f"Visual backtest configured: {params.ticker}")
        self._runner = VisualBacktestRunner(
            params,
            self.config,
            self.log,
            self.display_ctx,
            on_refresh=self._on_refresh,
            poll_key=self._poll_key,
        )
        self._runner.start()

    def _try_setup(self) -> None:
        params = self._run_setup()
        if params is None:
            return
        self._start_runner(params)

    def handle_key(self, event: Optional[str]) -> Optional[str]:
        if event == SCROLL_UP:
            self.log.scroll_up()
            self._on_refresh()
            return None
        if event == SCROLL_DOWN:
            self.log.scroll_down()
            self._on_refresh()
            return None
        if event == SCROLL_BOTTOM:
            self.log.scroll_to_bottom()
            self._on_refresh()
            return None
        if event == "r":
            self._setup_pending = True
            self._try_setup()
            return None
        if event in ("\r", "\n") and self.display_ctx.state == "idle":
            self._try_setup()
            return None
        if event == "q" and self.display_ctx.state == "waiting_next":
            if self._runner is not None:
                self._runner.stop()
            return None
        return event

    def tick(self) -> None:
        if self._runner is not None:
            pass  # runner refreshes via callbacks

    def stop(self) -> None:
        if self._runner is not None:
            self._runner.stop()
