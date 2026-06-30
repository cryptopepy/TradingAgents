"""Base protocol for workspace panes."""

from __future__ import annotations

from typing import Any, Optional, Protocol

from rich.console import Group


class Pane(Protocol):
    """One full-window view inside a workspace session."""

    pane_id: int
    title: str

    def focus(self) -> None:
        """Called when this pane becomes active."""

    def blur(self) -> None:
        """Called when switching away from this pane."""

    def render(self) -> Group:
        """Build the Rich layout for the current frame."""

    def handle_key(self, event: Optional[str]) -> Optional[str]:
        """Handle a key event; return passthrough key or None if consumed."""

    def tick(self) -> None:
        """Optional per-frame hook (animation, throttled refresh)."""
