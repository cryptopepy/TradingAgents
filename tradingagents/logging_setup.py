"""Optional file logging for long-running paper trading sessions."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from tradingagents.dataflows.config import get_config

_CONFIGURED = False
_ACTIVE_LOG_PATH: Optional[Path] = None

# Child loggers used for structured runtime tracing.
PAPER_RUNTIME_LOGGER = logging.getLogger("tradingagents.paper.runtime")
PAPER_DISPLAY_LOGGER = logging.getLogger("tradingagents.paper.display")


def resolve_paper_logs_dir(config: Optional[dict] = None) -> Path:
    """Directory for paper trading log files (default ``./logs``)."""
    cfg = config or get_config()
    explicit = cfg.get("paper_logs_dir") or os.getenv("TRADINGAGENTS_PAPER_LOGS_DIR")
    if explicit:
        return Path(os.path.expanduser(str(explicit))).resolve()
    return Path("logs").resolve()


def resolve_log_file_path(config: Optional[dict] = None) -> Path:
    """Return the on-disk debug log path (explicit or ``logs/paper_trading.log``)."""
    cfg = config or get_config()
    explicit = cfg.get("log_file_path") or os.getenv("TRADINGAGENTS_LOG_FILE")
    if explicit:
        return Path(os.path.expanduser(str(explicit))).resolve()
    return resolve_paper_logs_dir(cfg) / "paper_trading.log"


def configure_file_logging(config: Optional[dict] = None) -> Optional[Path]:
    """Enable rotating file logging when ``file_logging_enabled`` is set.

    Safe to call more than once; handlers are attached only once per process.
    """
    global _CONFIGURED, _ACTIVE_LOG_PATH

    cfg = config or get_config()
    if not cfg.get("file_logging_enabled"):
        return None

    log_path = resolve_log_file_path(cfg)
    if _CONFIGURED and _ACTIVE_LOG_PATH == log_path:
        return log_path

    log_path.parent.mkdir(parents=True, exist_ok=True)
    level_name = str(cfg.get("log_level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = RotatingFileHandler(
        log_path,
        maxBytes=int(cfg.get("log_file_max_bytes", 5_000_000)),
        backupCount=int(cfg.get("log_file_backup_count", 3)),
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.setLevel(level)

    root = logging.getLogger()
    if not _CONFIGURED:
        root.setLevel(min(root.level or logging.WARNING, level))
    # Avoid duplicate handlers pointing at the same file.
    abs_target = str(log_path)
    for existing in root.handlers:
        if isinstance(existing, RotatingFileHandler) and getattr(
            existing, "baseFilename", None
        ) == abs_target:
            _CONFIGURED = True
            _ACTIVE_LOG_PATH = log_path
            return log_path

    root.addHandler(handler)
    _CONFIGURED = True
    _ACTIVE_LOG_PATH = log_path

    logging.getLogger(__name__).info(
        "File logging enabled → %s (level=%s)", log_path, level_name
    )
    return log_path
