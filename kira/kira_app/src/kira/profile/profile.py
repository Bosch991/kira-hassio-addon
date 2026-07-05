"""Typed user profile model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AudioPreferences:
    """Audio input and output preferences."""

    input_device: str | None = None
    output_device: str | None = None
    mode: str = "local"


@dataclass(slots=True)
class HomeAssistantDefaults:
    """Default Home Assistant entities used by Kira."""

    media_player: str | None = None
    dashboard_url: str | None = None


@dataclass(slots=True)
class UserProfile:
    """Persistent user profile."""

    name: str = "Daniel"
    language: str = "de"
    timezone: str = "Europe/Berlin"
    preferences: dict[str, str] = field(default_factory=dict)
    audio: AudioPreferences = field(default_factory=AudioPreferences)
    homeassistant: HomeAssistantDefaults = field(default_factory=HomeAssistantDefaults)
    openai_model: str = "gpt-4.1-mini"
    voice: str | None = None
