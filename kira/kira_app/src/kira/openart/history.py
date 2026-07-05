"""Local OpenArt generation history."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OpenArtHistoryEntry:
    """One saved OpenArt generation entry."""

    timestamp: str
    prompt: str
    final_prompt: str
    path: str | None
    model_id: str | None
    style_id: str | None
    world_id: str | None
    project_id: str | None
    status: str


class OpenArtHistoryStore:
    """JSON-backed history for OpenArt generations."""

    def __init__(self, path: Path) -> None:
        """Initialize history storage."""
        self.path = path

    def initialize(self) -> None:
        """Create an empty history file if needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def add(
        self,
        *,
        prompt: str,
        final_prompt: str,
        path: Path | None,
        model_id: str | None,
        style_id: str | None,
        world_id: str | None,
        project_id: str | None,
        status: str,
    ) -> OpenArtHistoryEntry:
        """Append one generation entry."""
        self.initialize()
        entry = OpenArtHistoryEntry(
            timestamp=datetime.now(UTC).isoformat(),
            prompt=prompt,
            final_prompt=final_prompt,
            path=str(path) if path is not None else None,
            model_id=model_id,
            style_id=style_id,
            world_id=world_id,
            project_id=project_id,
            status=status,
        )
        entries = self.list_entries()
        entries.append(entry)
        self.path.write_text(
            json.dumps([asdict(item) for item in entries], indent=2),
            encoding="utf-8",
        )
        return entry

    def list_entries(self) -> list[OpenArtHistoryEntry]:
        """Return all history entries."""
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [OpenArtHistoryEntry(**item) for item in data if isinstance(item, dict)]
