"""Tests for optional file logging setup."""

from __future__ import annotations

import logging
import unittest
from pathlib import Path

from tradingagents.logging_setup import configure_file_logging, resolve_log_file_path


class TestFileLoggingSetup(unittest.TestCase):
    def test_can_be_disabled(self):
        path = configure_file_logging({"file_logging_enabled": False})
        self.assertIsNone(path)

    def test_enabled_by_default_in_config(self):
        from tradingagents.default_config import DEFAULT_CONFIG

        self.assertTrue(DEFAULT_CONFIG["file_logging_enabled"])
        self.assertTrue(DEFAULT_CONFIG["paper_journal_enabled"])

    def test_writes_to_configured_path(self):
        with self.subTest("enabled"):
            log_dir = Path(self._testMethodName) / "logs"
            cfg = {
                "file_logging_enabled": True,
                "log_file_path": str(log_dir / "paper.log"),
                "log_level": "INFO",
            }
            path = configure_file_logging(cfg)
            self.assertIsNotNone(path)
            assert path is not None
            logging.getLogger("tradingagents.paper.runtime").info("test runtime line")
            for handler in logging.getLogger().handlers:
                handler.flush()
            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            self.assertIn("test runtime line", content)

    def test_default_path_under_results_dir(self):
        cfg = {"results_dir": "/tmp/tradingagents-test-logs"}
        path = resolve_log_file_path(cfg)
        self.assertEqual(path.name, "paper_trading.log")
        self.assertIn("tradingagents-test-logs", str(path))


if __name__ == "__main__":
    unittest.main()
