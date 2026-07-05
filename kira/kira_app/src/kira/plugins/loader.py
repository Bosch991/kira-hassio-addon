"""Plugin discovery and loading helpers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from kira.plugins.base_plugin import BasePlugin, PluginManifest


def load_manifest(plugin_dir: Path) -> PluginManifest:
    """Load a plugin manifest from a plugin directory."""
    data = json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))
    return PluginManifest(
        name=str(data["name"]),
        version=str(data["version"]),
        description=str(data["description"]),
        author=str(data["author"]),
        dependencies=list(data.get("dependencies", [])),
        config_file=data.get("config_file"),
    )


def load_plugin_class(plugin_dir: Path) -> type[BasePlugin]:
    """Load the Plugin class from plugin.py."""
    plugin_file = plugin_dir / "plugin.py"
    module_name = f"kira_external_plugin_{plugin_dir.name}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load plugin module: {plugin_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin_class = getattr(module, "Plugin", None)
    if plugin_class is None:
        raise ImportError(f"Plugin class missing in {plugin_file}")
    if not issubclass(plugin_class, BasePlugin):
        raise TypeError(f"{plugin_file} Plugin must inherit BasePlugin")
    return plugin_class


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a simple YAML config file as a dictionary."""
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return _load_simple_yaml(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _load_simple_yaml(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", maxsplit=1)
        data[key.strip()] = _parse_scalar(value.strip())
    return data


def _parse_scalar(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value in {"[]", ""}:
        return [] if value == "[]" else ""
    return value.strip('"').strip("'")
