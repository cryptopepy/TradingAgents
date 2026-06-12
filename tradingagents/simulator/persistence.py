"""Local JSON persistence for paper trading sessions (PAPER-8)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from tradingagents.backtest.portfolio import VirtualPortfolio
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.symbol_utils import safe_path_key

logger = logging.getLogger(__name__)


def _merged_config(config: Optional[dict]) -> dict:
    cfg = get_config()
    if config:
        cfg = {**cfg, **config}
    return cfg


def paper_session_path(symbol: str, config: Optional[dict] = None) -> Path:
    cfg = _merged_config(config)
    root = Path(cfg["data_cache_dir"]) / "paper_sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{safe_path_key(symbol)}.json"


def save_paper_session(
    *,
    symbol: str,
    strategy_name: str,
    lookback: str,
    signal: str,
    portfolio: VirtualPortfolio,
    parameters: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    config: Optional[dict] = None,
) -> Path:
    """Persist portfolio and session metadata to JSON."""
    path = paper_session_path(symbol, config)
    payload = {
        "symbol": symbol,
        "strategy_name": strategy_name,
        "lookback": lookback,
        "signal": signal,
        "parameters": parameters or {},
        "initial_equity": portfolio.initial_equity,
        "cash": portfolio.cash,
        "equity": portfolio.equity,
        "positions": portfolio.positions,
        "last_prices": portfolio._last_prices,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "extra": extra or {},
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.debug("Saved paper session to %s", path)
    return path


def load_paper_session(symbol: str, config: Optional[dict] = None) -> Optional[dict]:
    """Load a saved session dict or return None if missing."""
    path = paper_session_path(symbol, config)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load paper session %s: %s", path, exc)
        return None


def restore_portfolio(data: dict) -> VirtualPortfolio:
    """Rebuild ``VirtualPortfolio`` from a persisted payload."""
    portfolio = VirtualPortfolio(
        initial_equity=float(data.get("initial_equity", 100_000.0)),
        fee_bps=float(data.get("fee_bps", 10.0)),
    )
    portfolio.cash = float(data.get("cash", portfolio.initial_equity))
    portfolio.equity = float(data.get("equity", portfolio.cash))
    portfolio.positions = dict(data.get("positions") or {})
    portfolio._last_prices = dict(data.get("last_prices") or {})
    return portfolio
