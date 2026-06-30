"""Cadence plugin registry."""

from __future__ import annotations

from typing import Dict, List

from .default_plugin import DefaultCadencePlugin
from .protocol import CadencePlugin

_REGISTRY: Dict[str, CadencePlugin] = {}
_DEFAULT = DefaultCadencePlugin()


def register_cadence_plugin(plugin: CadencePlugin) -> None:
    _REGISTRY[plugin.name] = plugin


def get_cadence_plugin(name: str | None = None) -> CadencePlugin:
    if name and name in _REGISTRY:
        return _REGISTRY[name]
    return _DEFAULT


def list_cadence_plugins() -> List[str]:
    return sorted(_REGISTRY.keys())
