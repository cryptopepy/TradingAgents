"""Tests for scroll / arrow key stdin parsing."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cli.keyboard_input import (
    SCROLL_BOTTOM,
    SCROLL_DOWN,
    SCROLL_UP,
    _parse_escape,
    _parse_mouse_wheel,
)


class TestKeyboardScrollEvents(unittest.TestCase):
    def test_parse_arrow_up(self):
        with patch("cli.keyboard_input._read_esc_sequence", return_value="[A"):
            self.assertEqual(_parse_escape(), SCROLL_UP)

    def test_parse_arrow_down(self):
        with patch("cli.keyboard_input._read_esc_sequence", return_value="[B"):
            self.assertEqual(_parse_escape(), SCROLL_DOWN)

    def test_parse_sgr_mouse_wheel(self):
        self.assertEqual(_parse_mouse_wheel("[<64;5;10M"), SCROLL_UP)
        self.assertEqual(_parse_mouse_wheel("[<65;5;10M"), SCROLL_DOWN)


if __name__ == "__main__":
    unittest.main()
