"""Live settings overlay — register plugins per TUI mode."""

from cli.tui.settings.core import (
    SettingField,
    SettingsContext,
    SettingsOverlay,
    SettingsPlugin,
    register_settings_plugin,
    settings_plugins_for,
)
from cli.tui.settings.paper import PaperSettingsPlugin, register_paper_settings

__all__ = [
    "PaperSettingsPlugin",
    "SettingField",
    "SettingsContext",
    "SettingsOverlay",
    "SettingsPlugin",
    "register_paper_settings",
    "register_settings_plugin",
    "settings_plugins_for",
]
