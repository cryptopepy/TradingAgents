"""Tests for modular settings overlay."""

from __future__ import annotations

import unittest
from io import StringIO
from unittest.mock import MagicMock

from rich.console import Console

from cli.tui.settings.core import SettingsContext, SettingsOverlay
from cli.tui.settings.paper import PaperSettingsPlugin, register_paper_settings


class TestSettingsOverlay(unittest.TestCase):
    def setUp(self) -> None:
        register_paper_settings()

    def test_paper_plugin_updates_stop_loss(self):
        engine = MagicMock()
        engine.session.stop_loss_pct = 0.02
        engine._spike_monitor.stop_loss_pct = 0.02
        cfg: dict = {"paper_stop_loss_pct": 0.02}
        ctx = SettingsContext(config=cfg, extras={"engine": engine})
        plugin = PaperSettingsPlugin()
        msg = plugin.write(ctx, "stop_loss", 0.03)
        self.assertEqual(engine.session.stop_loss_pct, 0.03)
        self.assertIn("3.0%", msg)

    def test_overlay_render_and_adjust(self):
        cfg = {
            "paper_stop_loss_pct": 0.02,
            "paper_activity_visible_lines": 11,
            "paper_activity_max_lines": 200,
        }
        overlay = SettingsOverlay(
            mode="paper",
            ctx=SettingsContext(config=cfg, extras={}),
            title="Test",
        )
        overlay.open()
        buffer = StringIO()
        Console(file=buffer, width=100).print(overlay.render_panel(width=80))
        rendered = buffer.getvalue()
        self.assertIn("Stop loss", rendered)
        overlay.handle_key(",")
        self.assertIn("updated", overlay.status.lower())

    def test_activity_max_lines_applies_to_log(self):
        from cli.activity_log import ActivityLog

        log = ActivityLog(max_lines=50)
        engine = MagicMock()
        engine.session.stop_loss_pct = 0.02
        engine.session.take_profit_pct = None
        engine.session.leverage = 1.0
        engine.adaptive_enabled = True
        engine._spike_monitor.enabled = True
        cfg = {"paper_activity_max_lines": 100}
        plugin = PaperSettingsPlugin()
        ctx = SettingsContext(config=cfg, extras={"engine": engine, "activity_log": log})
        plugin.write(ctx, "activity_max", 100)
        self.assertEqual(log._lines.maxlen, 100)


if __name__ == "__main__":
    unittest.main()
