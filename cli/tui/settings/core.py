"""Modular live settings overlay for Rich TUIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.keyboard_input import SCROLL_DOWN, SCROLL_LEFT, SCROLL_RIGHT, SCROLL_UP

_REGISTRY: dict[str, list["SettingsPlugin"]] = {}


def register_settings_plugin(mode: str, plugin: "SettingsPlugin") -> None:
    """Attach a settings plugin to a TUI mode (e.g. ``paper``)."""
    _REGISTRY.setdefault(mode, []).append(plugin)


def settings_plugins_for(mode: str) -> list["SettingsPlugin"]:
    return list(_REGISTRY.get(mode, []))


@dataclass
class SettingField:
    """One editable value exposed in the settings overlay."""

    id: str
    label: str
    section: str
    kind: str  # percent_fraction, percent, float, int, bool
    config_key: str
    step: float = 1.0
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    format_value: Optional[Callable[[Any], str]] = None
    parse_input: Optional[Callable[[float], Any]] = None


@dataclass
class SettingsContext:
    """Runtime bindings passed to plugins when reading/applying settings."""

    config: dict
    extras: dict = field(default_factory=dict)


class SettingsPlugin(Protocol):
    """Plugin interface — implement per TUI mode or feature area."""

    name: str

    def fields(self) -> list[SettingField]: ...

    def read(self, ctx: SettingsContext, field_id: str) -> Any: ...

    def write(self, ctx: SettingsContext, field_id: str, value: Any) -> str: ...


@dataclass
class _FlatField:
    plugin: SettingsPlugin
    field: SettingField


class SettingsOverlay:
    """Scrollable settings panel with keyboard editing."""

    def __init__(
        self,
        *,
        mode: str,
        ctx: SettingsContext,
        plugins: Optional[list[SettingsPlugin]] = None,
        title: str = "Settings",
    ) -> None:
        self.mode = mode
        self.ctx = ctx
        self.title = title
        self.is_open = False
        self.selected = 0
        self.status = ""
        self._plugins = plugins if plugins is not None else settings_plugins_for(mode)
        self._flat = self._flatten()

    def _flatten(self) -> list[_FlatField]:
        rows: list[_FlatField] = []
        for plugin in self._plugins:
            for spec in plugin.fields():
                rows.append(_FlatField(plugin=plugin, field=spec))
        return rows

    def open(self) -> None:
        self.is_open = True
        self.status = "↑↓ select · ←→ adjust · esc close"

    def close(self) -> None:
        self.is_open = False
        self.status = ""

    def _current(self) -> Optional[_FlatField]:
        if not self._flat:
            return None
        self.selected = max(0, min(self.selected, len(self._flat) - 1))
        return self._flat[self.selected]

    def _display_value(self, row: _FlatField) -> str:
        spec = row.field
        raw = row.plugin.read(self.ctx, spec.id)
        if spec.format_value is not None:
            return spec.format_value(raw)
        if spec.kind == "bool":
            return "on" if raw else "off"
        if spec.kind == "percent_fraction":
            return f"{float(raw) * 100:.1f}%"
        if spec.kind == "percent":
            return f"{float(raw):.1f}%"
        if spec.kind == "int":
            return str(int(raw))
        if spec.kind == "float":
            if float(raw).is_integer():
                return f"{int(raw)}"
            return f"{float(raw):.1f}"
        return str(raw)

    def _coerce_numeric(self, spec: SettingField, delta: float) -> Any:
        row = self._current()
        if row is None:
            return None
        current = row.plugin.read(self.ctx, spec.id)
        if spec.kind == "bool":
            return not bool(current)
        if spec.kind == "percent_fraction":
            base = float(current if current is not None else 0.0) * 100.0
        else:
            base = float(current if current is not None else 0.0)
        step = float(spec.step)
        value = base - step if delta < 0 else base + step
        if spec.min_value is not None:
            value = max(float(spec.min_value), value)
        if spec.max_value is not None:
            value = min(float(spec.max_value), value)
        if spec.parse_input is not None:
            return spec.parse_input(value)
        if spec.kind == "percent_fraction":
            return value / 100.0
        if spec.kind == "int":
            return int(round(value))
        if spec.kind == "percent":
            return float(value)
        return float(value)

    def adjust_selected(self, delta: float) -> None:
        row = self._current()
        if row is None:
            return
        spec = row.field
        new_value = self._coerce_numeric(spec, delta)
        message = row.plugin.write(self.ctx, spec.id, new_value)
        self.status = message or f"{spec.label} updated"

    def handle_key(self, key: Optional[str]) -> bool:
        """Return True when the key was consumed by the overlay."""
        if not self.is_open or key is None:
            return False
        if key in ("\x1b", "esc"):
            self.close()
            return True
        if key in ("s",):
            self.close()
            return True
        if key in (SCROLL_UP, "k"):
            self.selected = max(0, self.selected - 1)
            return True
        if key in (SCROLL_DOWN, "j"):
            self.selected = min(len(self._flat) - 1, self.selected + 1)
            return True
        if key in ("-", "_", "[", "h", ",", SCROLL_LEFT):
            self.adjust_selected(-1)
            return True
        if key in ("=", "+", "]", "l", ".", SCROLL_RIGHT):
            self.adjust_selected(1)
            return True
        return False

    def render_panel(self, *, width: Optional[int] = None) -> Panel:
        table = Table(
            show_header=True,
            header_style="bold magenta",
            expand=False,
            width=width,
        )
        table.add_column("Section", style="dim", width=14, no_wrap=True)
        table.add_column("Setting", width=22, no_wrap=True)
        table.add_column("Value", width=14, no_wrap=True)

        last_section = ""
        for idx, row in enumerate(self._flat):
            spec = row.field
            section = spec.section if spec.section != last_section else ""
            last_section = spec.section
            value = self._display_value(row)
            style = "bold white on dark_blue" if idx == self.selected else ""
            table.add_row(section, spec.label, value, style=style)

        footer = Text(
            self.status or "↑↓ select · ←→ or +/- adjust · esc close",
            style="dim",
        )
        body = Table.grid(expand=True)
        body.add_row(table)
        body.add_row(footer)
        return Panel(body, title=self.title, border_style="magenta", width=width)

    def footer_hint(self) -> str:
        return "(settings open — esc to close)"
