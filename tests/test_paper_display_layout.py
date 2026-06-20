"""Tests for paper live display layout sizing."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cli.paper_display import (
    activity_log_layout,
    clip_activity_message,
    paper_live_reserved_lines,
)


class TestPaperDisplayLayout(unittest.TestCase):
    def test_clip_activity_message(self):
        msg = "x" * 100
        clipped = clip_activity_message(msg, 40)
        self.assertEqual(len(clipped), 40)
        self.assertTrue(clipped.endswith("…"))

    def test_reserved_lines_grows_with_leverage(self):
        base = paper_live_reserved_lines()
        with_lev = paper_live_reserved_lines(leverage_on=True)
        self.assertGreater(with_lev, base)

    @patch("cli.paper_display.terminal_size", return_value=(120, 40))
    def test_activity_capped_by_config(self, _size):
        visible, panel_h = activity_log_layout(
            config={"paper_activity_visible_lines": 11},
        )
        self.assertLessEqual(visible, 11)
        self.assertEqual(panel_h, visible + 2)

    @patch("cli.paper_display.terminal_size", return_value=(120, 24))
    def test_activity_shrinks_on_short_terminal(self, _size):
        visible, _panel_h = activity_log_layout(
            config={"paper_activity_visible_lines": 11},
        )
        self.assertGreaterEqual(visible, 4)
        self.assertLess(visible, 11)


if __name__ == "__main__":
    unittest.main()
