"""Exchange top movers for paper-trading pair discovery (Kraken-first)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .coingecko import CoinGeckoAPIError, _api_key, _coingecko_get
from .kraken import fetch_kraken_mover_rows

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, "MoversSnapshot"]] = {}


@dataclass(frozen=True)
class MarketMover:
    """One ranked gainer or loser mapped to a spot pair."""

    rank: int
    symbol: str
    pair: str
    name: str
    change_pct: float
    volume_usd: float
    price_usd: float
    side: str  # "gainer" | "loser"


@dataclass(frozen=True)
class MoversSnapshot:
    gainers: tuple[MarketMover, ...]
    losers: tuple[MarketMover, ...]
    fetched_at: datetime
    source: str

    @property
    def hotkeys(self) -> tuple[MarketMover, ...]:
        """Up to nine movers for keys 1–9 (gainers first, then losers)."""
        combined: list[MarketMover] = []
        combined.extend(self.gainers[:5])
        combined.extend(self.losers[: max(0, 9 - len(combined))])
        return tuple(combined[:9])

    def pair_for_hotkey(self, index: int) -> str | None:
        hot = self.hotkeys
        if 0 <= index < len(hot):
            return hot[index].pair
        return None


def _rows_to_snapshot(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    source: str,
) -> MoversSnapshot:
    ranked = sorted(rows, key=lambda r: float(r["change_pct"]), reverse=True)
    gainers: list[MarketMover] = []
    for idx, row in enumerate(ranked[:limit], start=1):
        gainers.append(
            MarketMover(
                rank=idx,
                symbol=str(row["symbol"]),
                pair=str(row["pair"]),
                name=str(row.get("name") or row["symbol"]),
                change_pct=float(row["change_pct"]),
                volume_usd=float(row["volume_usd"]),
                price_usd=float(row["price_usd"]),
                side="gainer",
            )
        )
    losers_rows = sorted(rows, key=lambda r: float(r["change_pct"]))
    losers: list[MarketMover] = []
    for idx, row in enumerate(losers_rows[:limit], start=1):
        losers.append(
            MarketMover(
                rank=idx,
                symbol=str(row["symbol"]),
                pair=str(row["pair"]),
                name=str(row.get("name") or row["symbol"]),
                change_pct=float(row["change_pct"]),
                volume_usd=float(row["volume_usd"]),
                price_usd=float(row["price_usd"]),
                side="loser",
            )
        )
    return MoversSnapshot(
        gainers=tuple(gainers),
        losers=tuple(losers),
        fetched_at=datetime.now(timezone.utc),
        source=source,
    )


def _mover_from_coingecko_row(
    row: dict[str, Any], *, side: str, rank: int, min_volume: float
) -> MarketMover | None:
    symbol = str(row.get("symbol") or "").upper()
    if not symbol:
        return None
    volume = float(
        row.get("usd_24h_vol")
        or row.get("total_volume")
        or row.get("volume")
        or 0.0
    )
    if volume < min_volume:
        return None
    change = row.get("usd_24h_change")
    if change is None:
        change = row.get("price_change_percentage_24h")
    if change is None:
        return None
    price = float(row.get("usd") or row.get("current_price") or 0.0)
    name = str(row.get("name") or symbol)
    return MarketMover(
        rank=rank,
        symbol=symbol,
        pair=f"{symbol}/USDT",
        name=name,
        change_pct=float(change),
        volume_usd=volume,
        price_usd=price,
        side=side,
    )


def _parse_coingecko_dedicated(data: dict[str, Any], *, limit: int, min_volume: float) -> MoversSnapshot:
    gainers: list[MarketMover] = []
    for idx, row in enumerate(data.get("top_gainers") or [], start=1):
        mover = _mover_from_coingecko_row(row, side="gainer", rank=idx, min_volume=min_volume)
        if mover:
            gainers.append(mover)
        if len(gainers) >= limit:
            break
    losers: list[MarketMover] = []
    for idx, row in enumerate(data.get("top_losers") or [], start=1):
        mover = _mover_from_coingecko_row(row, side="loser", rank=idx, min_volume=min_volume)
        if mover:
            losers.append(mover)
        if len(losers) >= limit:
            break
    return MoversSnapshot(
        gainers=tuple(gainers),
        losers=tuple(losers),
        fetched_at=datetime.now(timezone.utc),
        source="coingecko_top_gainers_losers",
    )


def _fetch_coingecko_markets(*, limit: int, min_volume: float) -> MoversSnapshot:
    rows: list[dict[str, Any]] = []
    for page in (1, 2):
        batch = _coingecko_get(
            "/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "volume_desc",
                "per_page": 250,
                "page": page,
                "price_change_percentage": "24h",
            },
        )
        if isinstance(batch, list):
            rows.extend(batch)
    filtered = [r for r in rows if float(r.get("total_volume") or 0) >= min_volume]
    normalized = [
        {
            "symbol": str(r.get("symbol", "")).upper(),
            "pair": f"{str(r.get('symbol', '')).upper()}/USDT",
            "name": r.get("name"),
            "change_pct": float(r.get("price_change_percentage_24h") or 0),
            "volume_usd": float(r.get("total_volume") or 0),
            "price_usd": float(r.get("current_price") or 0),
        }
        for r in filtered
        if r.get("symbol")
    ]
    return _rows_to_snapshot(normalized, limit=limit, source="coingecko_markets")


def _fetch_coingecko(config: dict) -> MoversSnapshot | None:
    if not _api_key():
        return None
    limit = int(config.get("movers_display_limit", 5))
    min_volume = float(config.get("movers_min_volume_usd", 1_000_000))
    duration = str(config.get("movers_duration", "24h"))
    top_coins = str(config.get("movers_top_coins", "500"))
    try:
        data = _coingecko_get(
            "/coins/top_gainers_losers",
            params={
                "vs_currency": "usd",
                "duration": duration,
                "top_coins": top_coins,
            },
        )
        if isinstance(data, dict):
            snap = _parse_coingecko_dedicated(data, limit=limit, min_volume=min_volume)
            if snap.gainers or snap.losers:
                return snap
    except CoinGeckoAPIError as exc:
        logger.info("CoinGecko movers unavailable (%s)", exc)
    return _fetch_coingecko_markets(limit=limit, min_volume=min_volume)


def fetch_top_movers(config: dict | None = None, *, force_refresh: bool = False) -> MoversSnapshot:
    """Top gainers/losers with TTL cache. Kraken by default (no paid API)."""
    cfg = config or {}
    limit = int(cfg.get("movers_display_limit", 5))
    min_volume = float(cfg.get("movers_min_volume_usd", 250_000))
    provider = str(cfg.get("movers_provider", "kraken")).strip().lower()
    ttl = int(cfg.get("movers_cache_ttl_seconds", 300))
    cache_key = f"{provider}:{limit}:{min_volume}"

    if not force_refresh and cache_key in _CACHE:
        ts, snapshot = _CACHE[cache_key]
        if time.time() - ts <= ttl:
            return snapshot

    snapshot: MoversSnapshot | None = None
    errors: list[str] = []

    if provider in ("kraken", "auto"):
        try:
            rows = fetch_kraken_mover_rows(min_volume_usd=min_volume)
            if rows:
                from .kraken import kraken_credentials

                key_loaded = bool(kraken_credentials()[0])
                source = "kraken" + (" (API key)" if key_loaded else "")
                snapshot = _rows_to_snapshot(rows, limit=limit, source=source)
        except Exception as exc:
            errors.append(f"kraken: {exc}")
            logger.warning("Kraken movers fetch failed: %s", exc)

    if snapshot is None and provider in ("coingecko", "auto"):
        try:
            snapshot = _fetch_coingecko(cfg)
        except Exception as exc:
            errors.append(f"coingecko: {exc}")
            logger.warning("CoinGecko movers fetch failed: %s", exc)

    if snapshot is None or (not snapshot.gainers and not snapshot.losers):
        detail = "; ".join(errors) or "no liquid movers matched filters"
        raise RuntimeError(f"Could not load movers — {detail}")

    _CACHE[cache_key] = (time.time(), snapshot)
    return snapshot
