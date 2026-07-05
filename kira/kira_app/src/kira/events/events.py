"""Typed internal events emitted by Kira and plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Event:
    """Base event payload."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    source: str = "kira"


class ChatMessageReceived(Event):
    """Event emitted when a chat message enters Kira."""

    def __init__(self, message: str, *, source: str = "chat") -> None:
        """Create a chat message event."""
        Event.__init__(
            self,
            name="ChatMessageReceived",
            payload={"message": message},
            source=source,
        )


class VoiceGenerated(Event):
    """Event emitted after voice audio has been generated."""

    def __init__(self, path: str, *, source: str = "voice") -> None:
        """Create a voice generated event."""
        Event.__init__(
            self,
            name="VoiceGenerated",
            payload={"path": path},
            source=source,
        )


class HomeAssistantEvent(Event):
    """Event emitted for Home Assistant activity."""

    def __init__(self, summary: str, *, source: str = "homeassistant") -> None:
        """Create a Home Assistant event."""
        Event.__init__(
            self,
            name="HomeAssistantEvent",
            payload={"summary": summary},
            source=source,
        )


class MemorySaved(Event):
    """Event emitted when memory is saved."""

    def __init__(self, item_id: str, *, source: str = "memory") -> None:
        """Create a memory saved event."""
        Event.__init__(
            self,
            name="MemorySaved",
            payload={"item_id": item_id},
            source=source,
        )


class PluginLoaded(Event):
    """Event emitted after a plugin has loaded."""

    def __init__(self, plugin_name: str, *, source: str = "plugins") -> None:
        """Create a plugin loaded event."""
        Event.__init__(
            self,
            name="PluginLoaded",
            payload={"plugin_name": plugin_name},
            source=source,
        )


class PluginStopped(Event):
    """Event emitted after a plugin has stopped."""

    def __init__(self, plugin_name: str, *, source: str = "plugins") -> None:
        """Create a plugin stopped event."""
        Event.__init__(
            self,
            name="PluginStopped",
            payload={"plugin_name": plugin_name},
            source=source,
        )
