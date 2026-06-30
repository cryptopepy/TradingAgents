"""SQLite cache for backtest OHLCV ranges."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from tradingagents.dataflows.config import get_config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
  id INTEGER PRIMARY KEY,
  symbol TEXT NOT NULL,
  granularity_sec INTEGER NOT NULL,
  start_ts INTEGER NOT NULL,
  end_ts INTEGER NOT NULL,
  bar_count INTEGER NOT NULL,
  vendor TEXT,
  fetched_at REAL NOT NULL,
  UNIQUE(symbol, granularity_sec, start_ts, end_ts)
);
CREATE TABLE IF NOT EXISTS candles (
  dataset_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  open REAL,
  high REAL,
  low REAL,
  close REAL,
  volume REAL,
  PRIMARY KEY (dataset_id, ts),
  FOREIGN KEY (dataset_id) REFERENCES datasets(id)
);
CREATE INDEX IF NOT EXISTS idx_candles_ts ON candles(dataset_id, ts);
"""


def resolve_ohlcv_db_path(config: dict | None = None) -> Path:
    """Return path to the SQLite OHLCV database."""
    cfg = config or get_config()
    cache_dir = cfg.get("ohlcv_cache_dir")
    if not cache_dir:
        cache_dir = str(Path(cfg["data_cache_dir"]) / "ohlcv")
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path / "ohlcv.db"


def _to_unix(dt: datetime) -> int:
    ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.timestamp())


def _from_unix(ts: int) -> datetime:
    return pd.Timestamp(ts, unit="s", tz="UTC").tz_localize(None).to_pydatetime()


class OhlcvStore:
    """Persistent OHLCV cache keyed by symbol, granularity, and time range."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def get_cached(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        granularity_sec: int,
    ) -> pd.DataFrame | None:
        """Return cached OHLCV for an exact range, or None."""
        start_ts = _to_unix(start)
        end_ts = _to_unix(end)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM datasets
                WHERE symbol = ? AND granularity_sec = ?
                  AND start_ts = ? AND end_ts = ?
                """,
                (symbol, granularity_sec, start_ts, end_ts),
            ).fetchone()
            if row is None:
                return None
            dataset_id = int(row["id"])
            candles = conn.execute(
                """
                SELECT ts, open, high, low, close, volume
                FROM candles WHERE dataset_id = ?
                ORDER BY ts
                """,
                (dataset_id,),
            ).fetchall()
        if not candles:
            return None
        return self._rows_to_df(candles)

    def put(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        granularity_sec: int,
        df: pd.DataFrame,
        vendor: str,
    ) -> None:
        """Store OHLCV for an exact range."""
        if df is None or df.empty:
            return
        start_ts = _to_unix(start)
        end_ts = _to_unix(end)
        normalized = _normalize_df(df)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM datasets
                WHERE symbol = ? AND granularity_sec = ?
                  AND start_ts = ? AND end_ts = ?
                """,
                (symbol, granularity_sec, start_ts, end_ts),
            ).fetchone()
            if row is not None:
                dataset_id = int(row["id"])
                conn.execute("DELETE FROM candles WHERE dataset_id = ?", (dataset_id,))
                conn.execute(
                    """
                    UPDATE datasets
                    SET bar_count = ?, vendor = ?, fetched_at = ?
                    WHERE id = ?
                    """,
                    (len(normalized), vendor, time.time(), dataset_id),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO datasets
                    (symbol, granularity_sec, start_ts, end_ts, bar_count, vendor, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        granularity_sec,
                        start_ts,
                        end_ts,
                        len(normalized),
                        vendor,
                        time.time(),
                    ),
                )
                dataset_id = int(cur.lastrowid)
            conn.executemany(
                """
                INSERT INTO candles
                (dataset_id, ts, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        dataset_id,
                        _to_unix(pd.Timestamp(r["Date"]).to_pydatetime()),
                        float(r["Open"]),
                        float(r["High"]),
                        float(r["Low"]),
                        float(r["Close"]),
                        float(r.get("Volume", 0.0) or 0.0),
                    )
                    for _, r in normalized.iterrows()
                ],
            )
            conn.commit()

    def get_or_fetch(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        granularity_sec: int,
        fetch_fn: Callable[[], tuple[pd.DataFrame, str]],
        *,
        force_refresh: bool = False,
    ) -> tuple[pd.DataFrame, str]:
        """Return cached data or fetch once and persist."""
        if not force_refresh:
            cached = self.get_cached(symbol, start, end, granularity_sec)
            if cached is not None and len(cached) >= 30:
                return cached, "sqlite cache"

        df, vendor = fetch_fn()
        self.put(symbol, start, end, granularity_sec, df, vendor)
        return df, vendor

    @staticmethod
    def _rows_to_df(rows) -> pd.DataFrame:
        records = []
        for row in rows:
            records.append(
                {
                    "Date": _from_unix(int(row["ts"])),
                    "Open": float(row["open"]),
                    "High": float(row["high"]),
                    "Low": float(row["low"]),
                    "Close": float(row["close"]),
                    "Volume": float(row["volume"] or 0.0),
                }
            )
        return pd.DataFrame(records)


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)


def get_store(config: dict | None = None) -> OhlcvStore:
    """Return the default OHLCV store for the current config."""
    return OhlcvStore(resolve_ohlcv_db_path(config))
