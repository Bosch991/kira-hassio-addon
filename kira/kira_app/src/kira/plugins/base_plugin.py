"""Base classes for Kira plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Static plugin metadata loaded from manifest.json."""

    name: str
    version: str
    description: str
    author: str
    dependencies: list[str] = field(default_factory=list)
    config_file: str | None = None


@dataclass(frozen=True, slots=True)
class PluginHealth:
    """Healthcheck result for one plugin."""

    ok: bool
    message: str = "ok"
    details: dict[str, Any] = field(default_factory=dict)


class BasePlugin:
    """Base interface every Kira plugin implements."""

    def __init__(
        self,
        *,
        manifest: PluginManifest,
        config: dict[str, Any],
        context: Any,
        plugin_dir: Path,
    ) -> None:
        """Initialize plugin metadata, config, and runtime context."""
        self.manifest = manifest
        self.config = config
        self.context = context
        self.plugin_dir = plugin_dir
        self.started = False

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return self.manifest.name

    def start(self) -> None:
        """Start the plugin."""
        self.started = True

    def stop(self) -> None:
        """Stop the plugin."""
        self.started = False

    def healthcheck(self) -> PluginHealth:
        """Return plugin health."""
        state = "started" if self.started else "stopped"
        return PluginHealth(ok=True, message=state)
