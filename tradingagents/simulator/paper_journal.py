"""Append-only session and trade journal for paper trading."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tradingagents.dataflows.config import get_config
from tradingagents.logging_setup import resolve_paper_logs_dir

_LOCK = threading.Lock()
_ACTIVE: Optional["PaperJournal"] = None


def resolve_paper_journal_path(config: Optional[dict] = None) -> Path:
    """Default journal path under ``./logs``."""
    cfg = config or get_config()
    explicit = cfg.get("paper_journal_path") or os.getenv("TRADINGAGENTS_PAPER_JOURNAL_FILE")
    if explicit:
        return Path(os.path.expanduser(str(explicit))).resolve()
    return resolve_paper_logs_dir(cfg) / "paper_journal.log"


class PaperJournal:
    """Human-readable start/stop and trade log (enabled by default)."""

    def __init__(self, config: Optional[dict] = None) -> None:
        cfg = config or get_config()
        self.enabled = bool(cfg.get("paper_journal_enabled", True))
        self.path = resolve_paper_journal_path(cfg)
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, event: str, message: str) -> None:
        if not self.enabled or not message:
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"{timestamp} [{event}] {message}\n"
        with _LOCK:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def session_start(
        self,
        *,
        symbol: str,
        strategy: str,
        lookback: str,
        equity: float,
        leverage: float = 1.0,
        adaptive: bool = True,
        tick_interval: float = 3.0,
        resumed: bool = False,
    ) -> None:
        mode = "adaptive on" if adaptive else "adaptive off"
        lev = f"{leverage:g}x" if leverage > 1 else "1x"
        tag = "RESUME" if resumed else "START"
        self._write(
            tag,
            f"{symbol} | {strategy} ({lookback}) | equity ${equity:,.2f} | "
            f"leverage {lev} | {mode} | tick {tick_interval:.0f}s",
        )

    def session_stop(
        self,
        *,
        symbol: str,
        ticks: int,
        equity: float,
        reason: str = "ended",
    ) -> None:
        self._write(
            "STOP",
            f"{symbol} | {reason} | ticks={ticks} | equity ${equity:,.2f}",
        )

    def trade(self, message: str) -> None:
        self._write("TRADE", message)

    def note(self, message: str) -> None:
        """Optional lifecycle note (pair switch, strategy change)."""
        self._write("NOTE", message)


def configure_paper_journal(config: Optional[dict] = None) -> Optional[Path]:
    """Initialize the process-wide paper journal. Returns path when enabled."""
    global _ACTIVE
    journal = PaperJournal(config)
    if not journal.enabled:
        _ACTIVE = None
        return None
    _ACTIVE = journal
    return journal.path


def get_paper_journal() -> Optional[PaperJournal]:
    return _ACTIVE


def journal_session_start(**kwargs) -> None:
    if _ACTIVE is not None:
        _ACTIVE.session_start(**kwargs)


def journal_session_stop(**kwargs) -> None:
    if _ACTIVE is not None:
        _ACTIVE.session_stop(**kwargs)


def journal_trade(message: str) -> None:
    if _ACTIVE is not None:
        _ACTIVE.trade(message)


def journal_note(message: str) -> None:
    if _ACTIVE is not None:
        _ACTIVE.note(message)
