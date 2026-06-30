"""Workspace panes for multi-view terminal sessions."""

from cli.tui.panes.base import Pane
from cli.tui.panes.paper_pane import PaperPane
from cli.tui.panes.visual_backtest_pane import VisualBacktestPane

__all__ = ["Pane", "PaperPane", "VisualBacktestPane"]
