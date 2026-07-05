"""Runtime plugin manager."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from kira.events.events import PluginLoaded, PluginStopped
from kira.plugins.base_plugin import BasePlugin, PluginHealth, PluginManifest
from kira.plugins.loader import load_manifest, load_plugin_class, load_yaml_config


class PluginState(StrEnum):
    """Runtime state of a plugin."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass(slots=True)
class PluginRecord:
    """Loaded plugin metadata and runtime instance."""

    manifest: PluginManifest
    plugin_dir: Path
    instance: BasePlugin | None = None
    state: PluginState = PluginState.DISABLED
    error: str | None = None
    load_seconds: float = 0.0


class PluginManager:
    """Discover, start, stop, reload, and inspect plugins."""

    def __init__(
        self,
        *,
        plugins_dir: Path,
        config_dir: Path,
        context: Any,
    ) -> None:
        """Initialize the manager with plugin and config directories."""
        self.plugins_dir = plugins_dir
        self.config_dir = config_dir
        self.context = context
        self.records: dict[str, PluginRecord] = {}

    def discover(self) -> list[PluginManifest]:
        """Discover plugin manifests without starting plugins."""
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        manifests: list[PluginManifest] = []
        for plugin_dir in sorted(self.plugins_dir.iterdir()):
            if not plugin_dir.is_dir() or not (plugin_dir / "manifest.json").exists():
                continue
            manifest = load_manifest(plugin_dir)
            manifests.append(manifest)
            self.records.setdefault(
                manifest.name,
                PluginRecord(manifest=manifest, plugin_dir=plugin_dir),
            )
        return manifests

    def load_all(self) -> None:
        """Discover and start every enabled plugin."""
        for manifest in self.discover():
            config = self._plugin_config(manifest)
            if bool(config.get("enabled", True)):
                self.enable(manifest.name)
            else:
                record = self.records[manifest.name]
                record.state = PluginState.DISABLED

    def list_plugins(self) -> list[PluginRecord]:
        """Return all known plugins."""
        return list(self.records.values())

    def get(self, name: str) -> PluginRecord | None:
        """Return one plugin record by name."""
        return self.records.get(name)

    def enable(self, name: str) -> PluginRecord:
        """Enable and start one plugin."""
        record = self._require_record(name)
        self._set_enabled(record.manifest, enabled=True)
        started = time.perf_counter()
        try:
            config = self._plugin_config(record.manifest)
            plugin_class = load_plugin_class(record.plugin_dir)
            instance = plugin_class(
                manifest=record.manifest,
                config=config,
                context=self.context,
                plugin_dir=record.plugin_dir,
            )
            instance.start()
            record.instance = instance
            record.state = PluginState.ENABLED
            record.error = None
            record.load_seconds = time.perf_counter() - started
            self._publish(PluginLoaded(record.manifest.name))
            self._record_load_time(record.manifest.name, record.load_seconds)
            return record
        except Exception as exc:
            record.state = PluginState.ERROR
            record.error = str(exc)
            record.load_seconds = time.perf_counter() - started
            return record

    def disable(self, name: str) -> PluginRecord:
        """Disable and stop one plugin."""
        record = self._require_record(name)
        self._set_enabled(record.manifest, enabled=False)
        if record.instance is not None:
            record.instance.stop()
            self._publish(PluginStopped(record.manifest.name))
        record.instance = None
        record.state = PluginState.DISABLED
        return record

    def reload(self, name: str) -> PluginRecord:
        """Reload one plugin."""
        self.disable(name)
        return self.enable(name)

    def reload_all(self) -> list[PluginRecord]:
        """Reload all enabled plugins."""
        return [
            self.reload(record.manifest.name)
            for record in self.list_plugins()
            if record.state is PluginState.ENABLED
        ]

    def health(self) -> dict[str, PluginHealth]:
        """Run healthchecks for all known plugins."""
        results: dict[str, PluginHealth] = {}
        for record in self.list_plugins():
            if record.instance is None:
                results[record.manifest.name] = PluginHealth(
                    ok=record.state is not PluginState.ERROR,
                    message=record.error or record.state.value,
                )
                continue
            results[record.manifest.name] = record.instance.healthcheck()
        return results

    def _plugin_config(self, manifest: PluginManifest) -> dict[str, Any]:
        name = manifest.config_file or f"{manifest.name}.yaml"
        return load_yaml_config(self.config_dir / name)

    def _set_enabled(self, manifest: PluginManifest, *, enabled: bool) -> None:
        name = manifest.config_file or f"{manifest.name}.yaml"
        path = self.config_dir / name
        config = self._plugin_config(manifest)
        config["enabled"] = enabled
        lines = [f"{key}: {str(value).lower()}" for key, value in config.items()]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _require_record(self, name: str) -> PluginRecord:
        if name not in self.records:
            self.discover()
        record = self.records.get(name)
        if record is None:
            raise KeyError(f"Plugin not found: {name}")
        return record

    def _publish(self, event: PluginLoaded | PluginStopped) -> None:
        event_bus = getattr(self.context, "event_bus", None)
        if event_bus is not None:
            event_bus.publish(event)

    def _record_load_time(self, name: str, seconds: float) -> None:
        telemetry = getattr(self.context, "telemetry", None)
        if telemetry is not None:
            telemetry.record_plugin_load(name, seconds)
