"""Paper-trading settings plugin."""

from __future__ import annotations

from typing import Any, Optional

from cli.tui.settings.core import (
    SettingField,
    SettingsContext,
    SettingsPlugin,
    register_settings_plugin,
)

_FIELD_INDEX: dict[str, SettingField] = {}


def _fmt_tp(value: Any) -> str:
    if value is None:
        return "auto (2× SL)"
    return f"{float(value) * 100:.1f}%"


def _parse_tp(value: float) -> Any:
    if value <= 0:
        return None
    return value / 100.0


class PaperSettingsPlugin:
    """Editable paper session + UI knobs."""

    name = "paper"

    def fields(self) -> list[SettingField]:
        return [
            SettingField(
                id="stop_loss",
                label="Stop loss",
                section="Risk",
                kind="percent_fraction",
                config_key="paper_stop_loss_pct",
                step=0.5,
                min_value=0.5,
                max_value=20.0,
            ),
            SettingField(
                id="take_profit",
                label="Take profit",
                section="Risk",
                kind="percent_fraction",
                config_key="paper_take_profit_pct",
                step=0.5,
                min_value=0.0,
                max_value=50.0,
                format_value=_fmt_tp,
                parse_input=_parse_tp,
            ),
            SettingField(
                id="leverage",
                label="Leverage",
                section="Risk",
                kind="float",
                config_key="paper_leverage",
                step=1.0,
                min_value=1.0,
                max_value=10.0,
            ),
            SettingField(
                id="tick_interval",
                label="Tick interval",
                section="Session",
                kind="float",
                config_key="paper_tick_interval_seconds",
                step=1.0,
                min_value=1.0,
                max_value=120.0,
            ),
            SettingField(
                id="max_drawdown",
                label="Drawdown cap",
                section="Adaptive",
                kind="percent",
                config_key="max_allowed_drawdown_pct",
                step=0.5,
                min_value=1.0,
                max_value=25.0,
            ),
            SettingField(
                id="adaptive",
                label="Adaptive review",
                section="Adaptive",
                kind="bool",
                config_key="paper_adaptive_enabled",
            ),
            SettingField(
                id="spike_review",
                label="Fast-move review",
                section="Adaptive",
                kind="bool",
                config_key="paper_spike_review_enabled",
            ),
            SettingField(
                id="activity_visible",
                label="Log visible rows",
                section="Display",
                kind="int",
                config_key="paper_activity_visible_lines",
                step=1.0,
                min_value=4.0,
                max_value=30.0,
            ),
            SettingField(
                id="activity_max",
                label="Log history rows",
                section="Display",
                kind="int",
                config_key="paper_activity_max_lines",
                step=25.0,
                min_value=20.0,
                max_value=1000.0,
            ),
            SettingField(
                id="heartbeat",
                label="Status heartbeat",
                section="Display",
                kind="float",
                config_key="paper_status_heartbeat_minutes",
                step=1.0,
                min_value=0.0,
                max_value=60.0,
            ),
        ]

    def _field(self, field_id: str) -> SettingField:
        if not _FIELD_INDEX:
            for spec in self.fields():
                _FIELD_INDEX[spec.id] = spec
        return _FIELD_INDEX[field_id]

    def read(self, ctx: SettingsContext, field_id: str) -> Any:
        spec = self._field(field_id)
        cfg = ctx.config
        engine = ctx.extras.get("engine")
        if field_id == "stop_loss":
            if engine is not None:
                return float(engine.session.stop_loss_pct)
            return float(cfg.get(spec.config_key, 0.02))
        if field_id == "take_profit":
            if engine is not None:
                return engine.session.take_profit_pct
            return cfg.get(spec.config_key)
        if field_id == "leverage":
            if engine is not None:
                return float(engine.session.leverage or 1.0)
            return float(cfg.get(spec.config_key, 1.0))
        if field_id == "adaptive":
            if engine is not None:
                return bool(engine.adaptive_enabled)
            return bool(cfg.get(spec.config_key, True))
        if field_id == "spike_review":
            if engine is not None:
                return bool(engine._spike_monitor.enabled)
            return bool(cfg.get(spec.config_key, True))
        value = cfg.get(spec.config_key)
        if value is None:
            defaults = {
                "paper_tick_interval_seconds": 3.0,
                "max_allowed_drawdown_pct": 5.0,
                "paper_activity_visible_lines": 11,
                "paper_activity_max_lines": 200,
                "paper_status_heartbeat_minutes": 10.0,
            }
            value = defaults.get(spec.config_key, 0 if spec.kind == "int" else 0.0)
        return value

    def write(self, ctx: SettingsContext, field_id: str, value: Any) -> str:
        spec = self._field(field_id)
        cfg = ctx.config
        engine = ctx.extras.get("engine")
        display_ctx = ctx.extras.get("display_ctx")
        activity_log = ctx.extras.get("activity_log")

        cfg[spec.config_key] = value

        if field_id == "stop_loss" and engine is not None:
            engine.session.stop_loss_pct = float(value)
            engine.config["paper_stop_loss_pct"] = float(value)
            engine._spike_monitor.stop_loss_pct = float(value)
            return f"Stop loss → {float(value) * 100:.1f}%"

        if field_id == "take_profit" and engine is not None:
            engine.session.take_profit_pct = value
            engine.config["paper_take_profit_pct"] = value
            if value is None:
                return "Take profit → auto (2× SL)"
            return f"Take profit → {float(value) * 100:.1f}%"

        if field_id == "leverage" and engine is not None:
            lev = max(1.0, float(value))
            engine.session.leverage = lev
            engine.portfolio.default_leverage = lev
            engine.config["paper_leverage"] = lev
            return f"Leverage → {lev:g}x (new entries)"

        if field_id == "tick_interval":
            if display_ctx is not None:
                display_ctx.tick_interval = float(value)
            if engine is not None:
                engine.config["paper_tick_interval_seconds"] = float(value)
            return f"Tick interval → {float(value):.0f}s"

        if field_id == "max_drawdown" and engine is not None:
            pct = float(value)
            engine._adaptive.loss_threshold_pct = pct
            engine.config["max_allowed_drawdown_pct"] = pct
            engine.config["paper_loss_threshold_pct"] = pct
            return f"Drawdown cap → {pct:.1f}%"

        if field_id == "adaptive" and engine is not None:
            engine.adaptive_enabled = bool(value)
            engine.config["paper_adaptive_enabled"] = bool(value)
            spike_on = bool(value) and bool(cfg.get("paper_spike_review_enabled", True))
            engine._spike_monitor.enabled = spike_on
            return f"Adaptive review → {'on' if value else 'off'}"

        if field_id == "spike_review" and engine is not None:
            enabled = bool(value) and bool(engine.adaptive_enabled)
            engine._spike_monitor.enabled = enabled
            engine.config["paper_spike_review_enabled"] = bool(value)
            return f"Fast-move review → {'on' if enabled else 'off'}"

        if field_id == "activity_visible":
            return f"Log visible rows → {int(value)} (live)"

        if field_id == "activity_max" and activity_log is not None:
            activity_log.set_max_lines(int(value))
            return f"Log history → {int(value)} rows"

        if field_id == "heartbeat" and engine is not None:
            engine.config["paper_status_heartbeat_minutes"] = float(value)
            label = "off" if float(value) <= 0 else f"{float(value):.0f}m"
            return f"Status heartbeat → {label}"

        return f"{spec.label} updated"


def register_paper_settings() -> None:
    register_settings_plugin("paper", PaperSettingsPlugin())
