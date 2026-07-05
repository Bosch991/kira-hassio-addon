"""Build the final system prompt from personality fragments."""

from __future__ import annotations

from kira.personality.personality import PersonalityProfile


class PromptBuilder:
    """Compose Kira's system prompt without hard-coded personality text."""

    def __init__(self, profile: PersonalityProfile) -> None:
        """Initialize the builder with a loaded personality profile."""
        self.profile = profile

    def build(self) -> str:
        """Return the complete system prompt."""
        sections = [
            content for content in self.profile.fragments.values() if content.strip()
        ]
        return "\n\n---\n\n".join(sections)
