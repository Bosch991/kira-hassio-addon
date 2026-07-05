"""JSON-backed profile storage."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from kira.profile.profile import (
    AudioPreferences,
    HomeAssistantDefaults,
    UserProfile,
)


class ProfileStore:
    """Load and save the local user profile."""

    def __init__(self, path: Path) -> None:
        """Initialize profile storage."""
        self.path = path

    def load(self) -> UserProfile:
        """Load the profile, creating a default profile if needed."""
        if not self.path.exists():
            profile = UserProfile()
            self.save(profile)
            return profile
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return UserProfile(
            name=data.get("name", "Daniel"),
            language=data.get("language", "de"),
            timezone=data.get("timezone", "Europe/Berlin"),
            preferences=dict(data.get("preferences", {})),
            audio=AudioPreferences(**dict(data.get("audio", {}))),
            homeassistant=HomeAssistantDefaults(**dict(data.get("homeassistant", {}))),
            openai_model=data.get("openai_model", "gpt-4.1-mini"),
            voice=data.get("voice"),
        )

    def save(self, profile: UserProfile) -> None:
        """Save the profile."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(profile), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
