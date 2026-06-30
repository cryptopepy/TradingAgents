"""Tests for workspace manager."""

from cli.tui.panes.base import Pane
from cli.tui.workspace import WorkspaceManager
from rich.console import Group


class _StubPane:
    pane_id = 1
    title = "stub"

    def __init__(self, pid: int):
        self.pane_id = pid
        self.focused = False
        self.keys: list = []

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False

    def render(self) -> Group:
        return Group(f"pane-{self.pane_id}")

    def handle_key(self, event):
        self.keys.append(event)
        return None

    def tick(self) -> None:
        pass


def test_workspace_switches_panes():
    p1 = _StubPane(1)
    p2 = _StubPane(2)
    ws = WorkspaceManager({1: p1, 2: p2})
    assert ws.active_pane_id == 1
    assert ws.handle_pane_key("__pane_2__")
    assert ws.active_pane_id == 2
    assert p1.focused is False
    assert p2.focused is True
