"""Tests for paper session/trade journal."""

from __future__ import annotations

import unittest
from pathlib import Path

from tradingagents.simulator.paper_journal import (
    PaperJournal,
    configure_paper_journal,
    journal_session_start,
    journal_session_stop,
    journal_trade,
)


class TestPaperJournal(unittest.TestCase):
    def test_disabled_writes_nothing(self):
        log_path = Path(self._testMethodName) / "journal.log"
        journal = PaperJournal(
            {"paper_journal_enabled": False, "paper_journal_path": str(log_path)}
        )
        journal.session_start(
            symbol="BTC/USDT",
            strategy="test",
            lookback="24h",
            equity=10_000.0,
        )
        self.assertFalse(log_path.exists())

    def test_start_stop_and_trade(self):
        log_path = Path(self._testMethodName) / "journal.log"
        configure_paper_journal(
            {"paper_journal_enabled": True, "paper_journal_path": str(log_path)}
        )
        journal_session_start(
            symbol="BTC/USDT",
            strategy="cci_breakout",
            lookback="7d",
            equity=10_000.0,
            leverage=2.0,
        )
        journal_trade("BUY — enter long @ $60,000.00 · 2x — equity $10,000.00")
        journal_session_stop(
            symbol="BTC/USDT",
            ticks=42,
            equity=9_500.0,
            reason="quit (q)",
        )
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("[START]", content)
        self.assertIn("BTC/USDT", content)
        self.assertIn("leverage 2x", content)
        self.assertIn("[TRADE]", content)
        self.assertIn("BUY — enter long", content)
        self.assertIn("[STOP]", content)
        self.assertIn("ticks=42", content)
        self.assertIn("quit (q)", content)


if __name__ == "__main__":
    unittest.main()
