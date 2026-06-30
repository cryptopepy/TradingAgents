"""Multi-pane workspace for paper trading sessions."""

from __future__ import annotations

from typing import Callable, Optional

from rich.console import Group
from rich.text import Text

from cli.keyboard_input import (
    PANE_1,
    PANE_2,
    PANE_3,
    PANE_4,
    PANE_5,
    PANE_6,
    PANE_7,
    PANE_8,
    PANE_9,
)
from cli.tui.panes.base import Pane

_PANE_KEYS = {
    PANE_1: 1,
    PANE_2: 2,
    PANE_3: 3,
    PANE_4: 4,
    PANE_5: 5,
    PANE_6: 6,
    PANE_7: 7,
    PANE_8: 8,
    PANE_9: 9,
}

WORKSPACE_FOOTER = "(Ctrl+1) paper · (Ctrl+2) backtest"


class WorkspaceManager:
    """Routes render and keyboard events to the active pane."""

    def __init__(
        self,
        panes: dict[int, Pane],
        *,
        on_switch: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        if not panes:
            raise ValueError("Workspace requires at least one pane")
        self._panes = dict(panes)
        self._active = min(self._panes)
        self._on_switch = on_switch
        self._panes[self._active].focus()

    @property
    def active_pane_id(self) -> int:
        return self._active

    @property
    def active_pane(self) -> Pane:
        return self._panes[self._active]

    def switch_pane(self, pane_id: int) -> bool:
        """Switch to ``pane_id`` if registered. Returns True when changed."""
        if pane_id not in self._panes or pane_id == self._active:
            return False
        old = self._active
        self._panes[old].blur()
        self._active = pane_id
        self._panes[pane_id].focus()
        if self._on_switch is not None:
            self._on_switch(old, pane_id)
        return True

    def handle_pane_key(self, event: Optional[str]) -> bool:
        """Handle Ctrl+N pane switches. Returns True if consumed."""
        target = _PANE_KEYS.get(event or "")
        if target is None:
            return False
        return self.switch_pane(target)

    def handle_key(self, event: Optional[str]) -> Optional[str]:
        if self.handle_pane_key(event):
            return None
        return self.active_pane.handle_key(event)

    def render(self) -> Group:
        content = self.active_pane.render()
        footer = Text(WORKSPACE_FOOTER, style="dim")
        if isinstance(content, Group):
            return Group(*content.renderables, footer)
        return Group(content, footer)

    def tick(self) -> None:
        self.active_pane.tick()
