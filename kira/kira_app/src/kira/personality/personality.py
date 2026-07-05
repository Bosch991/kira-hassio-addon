"""Personality profile loaded from markdown prompt fragments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PersonalityProfile:
    """Collection of markdown prompt fragments describing Kira."""

    fragments: dict[str, str]

    @classmethod
    def load(cls, prompts_dir: Path) -> PersonalityProfile:
        """Load all configured personality fragments from disk."""
        fragments: dict[str, str] = {}
        for name in (
            "personality.md",
            "behaviour.md",
            "greeting.md",
            "humour.md",
            "knowledge.md",
        ):
            path = prompts_dir / name
            if path.exists():
                fragments[name] = path.read_text(encoding="utf-8").strip()
            else:
                fragments[name] = ""
        return cls(fragments=fragments)

    @property
    def loaded_files(self) -> list[str]:
        """Return personality files that contained prompt text."""
        return [name for name, content in self.fragments.items() if content]
