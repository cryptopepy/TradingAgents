"""Smart Trading overlay — cadence × risk two-axis menu (key g)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.keyboard_input import SCROLL_LEFT, SCROLL_RIGHT
from tradingagents.simulator.smart_trading.profiles import RiskMode, TradingCadence
from tradingagents.simulator.smart_trading.runtime import export_profile

CADENCE_ORDER = [
    TradingCadence.SWING,
    TradingCadence.INTRADAY,
    TradingCadence.SCALP,
    TradingCadence.ADAPTIVE,
]
CADENCE_LABELS = {
    TradingCadence.SWING: "Swing",
    TradingCadence.INTRADAY: "Intraday",
    TradingCadence.SCALP: "Scalp",
    TradingCadence.ADAPTIVE: "Adaptive",
}
CADENCE_KEYS = {
    "s": TradingCadence.SWING,
    "i": TradingCadence.INTRADAY,
    "c": TradingCadence.SCALP,
    "a": TradingCadence.ADAPTIVE,
}
RISK_ORDER = [RiskMode.CONSERVATIVE, RiskMode.MODERATE, RiskMode.AGGRESSIVE]
RISK_LABELS = {
    RiskMode.CONSERVATIVE: "Conservative",
    RiskMode.MODERATE: "Moderate",
    RiskMode.AGGRESSIVE: "Aggressive",
}
RISK_KEYS = {"1": RiskMode.CONSERVATIVE, "2": RiskMode.MODERATE, "3": RiskMode.AGGRESSIVE}


@dataclass
class SmartTradingContext:
    config: dict
    extras: dict = field(default_factory=dict)


class SmartTradingOverlay:
    """Two-level cadence/risk popup for paper trading."""

    def __init__(
        self,
        *,
        ctx: SmartTradingContext,
        title: str = "Smart Trading",
        on_apply: Optional[Callable[[], str]] = None,
    ) -> None:
        self.ctx = ctx
        self.title = title
        self.on_apply = on_apply
        self.is_open = False
        self.status = ""
        self._cadence_idx = 0
        self._risk_idx = 1
        self._focus = 0  # 0=cadence, 1=risk
        self._sync_from_config()

    def _sync_from_config(self) -> None:
        cad = str(self.ctx.config.get("smart_trading_cadence", "swing")).lower()
        risk = str(self.ctx.config.get("smart_trading_risk", "moderate")).lower()
        for i, c in enumerate(CADENCE_ORDER):
            if c.value == cad:
                self._cadence_idx = i
                break
        for i, r in enumerate(RISK_ORDER):
            if r.value == risk:
                self._risk_idx = i
                break

    def open(self) -> None:
        self.is_open = True
        self.status = ""
        self._sync_from_config()

    def close(self) -> None:
        self.is_open = False
        self.status = ""

    def _preview_effective(self):
        engine = self.ctx.extras.get("engine")
        if engine is None:
            return None
        lev = float(getattr(engine.session, "leverage", 1.0) or 1.0)
        cadence = CADENCE_ORDER[self._cadence_idx].value
        risk = RISK_ORDER[self._risk_idx].value
        return engine._smart.resolve(
            lev,
            enabled=True,
            cadence=cadence,
            risk=risk,
        )

    def _apply(self) -> None:
        cfg = self.ctx.config
        cfg["smart_trading_enabled"] = True
        cfg["smart_trading_cadence"] = CADENCE_ORDER[self._cadence_idx].value
        cfg["smart_trading_risk"] = RISK_ORDER[self._risk_idx].value
        engine = self.ctx.extras.get("engine")
        if engine is not None:
            msg = engine.apply_smart_trading(
                enabled=True,
                cadence=cfg["smart_trading_cadence"],
                risk=cfg["smart_trading_risk"],
            )
            self.status = msg
            self._export_profile(cfg)
        elif self.on_apply:
            self.status = self.on_apply()
        else:
            self.status = "Applied (no engine bound)"

    def _disable(self) -> None:
        self.ctx.config["smart_trading_enabled"] = False
        engine = self.ctx.extras.get("engine")
        if engine is not None:
            self.status = engine.apply_smart_trading(enabled=False)
        else:
            self.status = "Smart Trading off"

    def _export_profile(self, cfg: dict) -> None:
        path = Path.home() / ".tradingagents" / "profiles" / (
            f"{cfg.get('smart_trading_cadence', 'swing')}_{cfg.get('smart_trading_risk', 'moderate')}.json"
        )
        try:
            export_profile(
                path,
                {
                    "cadence": cfg.get("smart_trading_cadence"),
                    "risk": cfg.get("smart_trading_risk"),
                    "enabled": cfg.get("smart_trading_enabled"),
                },
            )
        except OSError:
            pass

    def _shift_cadence(self, delta: int) -> None:
        self._cadence_idx = (self._cadence_idx + delta) % len(CADENCE_ORDER)

    def _shift_risk(self, delta: int) -> None:
        self._risk_idx = (self._risk_idx + delta) % len(RISK_ORDER)

    def handle_key(self, key: Optional[str]) -> bool:
        if not self.is_open or key is None:
            return False
        if key in ("\x1b", "esc", "g"):
            self.close()
            return True
        if key in ("o",):
            self._disable()
            return True
        if key in ("\r", "\n"):
            self._apply()
            return True
        if key in CADENCE_KEYS:
            self._cadence_idx = CADENCE_ORDER.index(CADENCE_KEYS[key])
            self._focus = 0
            return True
        if key in RISK_KEYS:
            self._risk_idx = RISK_ORDER.index(RISK_KEYS[key])
            self._focus = 1
            return True
        if key in (SCROLL_LEFT, "h", "-", "_"):
            if self._focus == 0:
                self._shift_cadence(-1)
            else:
                self._shift_risk(-1)
            return True
        if key in (SCROLL_RIGHT, "l", "+", "="):
            if self._focus == 0:
                self._shift_cadence(1)
            else:
                self._shift_risk(1)
            return True
        if key in ("k",):
            self._focus = max(0, self._focus - 1)
            return True
        if key in ("j",):
            self._focus = min(1, self._focus + 1)
            return True
        return False

    def render_panel(self, *, width: Optional[int] = None) -> Panel:
        cfg = self.ctx.config
        enabled = bool(cfg.get("smart_trading_enabled", False))
        engine = self.ctx.extras.get("engine")
        symbol = getattr(engine.session, "symbol", "—") if engine else "—"
        lev = float(getattr(engine.session, "leverage", 1.0) or 1.0) if engine else 1.0
        status_line = "ENABLED" if enabled else "OFF (preview)"

        table = Table(show_header=False, expand=False, width=width, pad_edge=False)
        table.add_column(width=14, style="dim")
        table.add_column()

        cadence_row = " · ".join(
            f"[bold cyan]▶ {CADENCE_LABELS[c]}[/]" if i == self._cadence_idx else CADENCE_LABELS[c]
            for i, c in enumerate(CADENCE_ORDER)
        )
        risk_row = " · ".join(
            f"[bold yellow]▶ {RISK_LABELS[r]}[/]" if i == self._risk_idx else RISK_LABELS[r]
            for i, r in enumerate(RISK_ORDER)
        )
        cad_style = "bold white on dark_blue" if self._focus == 0 else ""
        risk_style = "bold white on dark_blue" if self._focus == 1 else ""
        table.add_row("CADENCE", cadence_row, style=cad_style)
        table.add_row("", "(←→ or S/I/C/A)", style="dim")
        table.add_row("RISK", risk_row, style=risk_style)
        table.add_row("", "(1/2/3)", style="dim")

        eff = self._preview_effective()
        if eff is not None:
            table.add_row(
                "Effective",
                (
                    f"{eff.signal_lookback} signals · SL {eff.stop_loss_pct * 100:.2f}% · "
                    f"TP {eff.take_profit_pct * 100:.2f}% · size {eff.position_size_pct * 100:.0f}%"
                ),
            )
            table.add_row(
                "Guards",
                (
                    f"max {eff.max_daily_trades}/day · liq {eff.liquidation_guard_pct * 100:.0f}% · "
                    f"cooldown {eff.consecutive_loss_limit} losses"
                ),
            )
        state = engine.get_state() if engine else None
        if state is not None:
            table.add_row(
                "Session",
                (
                    f"trades today {state.daily_trade_count} · "
                    f"ATR rank {state.atr_rank_pct:.0f}% · signal {state.signal}"
                ),
            )
            if state.open_position and state.break_even_pct is not None:
                table.add_row(
                    "Break-even",
                    f"needs +{state.break_even_pct:.3f}% to cover fees",
                )

        footer = Text(
            self.status
            or "(Enter) apply · (o) off · (g/esc) close",
            style="dim",
        )
        body = Table.grid(expand=True)
        body.add_row(Text(f"{symbol} · {lev:.0f}x leverage · {status_line}", style="bold"))
        body.add_row(table)
        body.add_row(footer)
        return Panel(body, title=self.title, border_style="green", width=width)

    def footer_hint(self) -> str:
        return "(smart trading — Enter apply · o off · g/esc close)"
