"""JSON-backed local memory storage."""

from __future__ import annotations

import json
from pathlib import Path

from kira.memory.models import MemoryDocument, MemoryItem, MemoryKind, utc_now


class MemoryStore:
    """Persist conversation notes and project knowledge as local JSON."""

    def __init__(self, path: Path) -> None:
        """Initialize the store with the JSON document path."""
        self.path = path

    def initialize(self) -> None:
        """Create the memory file when it does not exist."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_document(MemoryDocument())

    def add_item(
        self,
        *,
        kind: MemoryKind,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> MemoryItem:
        """Add a new item and return the persisted model."""
        document = self._read_document()
        item = MemoryItem(
            kind=kind,
            title=title,
            content=content,
            tags=tags or [],
        )
        document.items.append(item)
        self._write_document(document)
        return item

    def add_conversation_note(
        self,
        content: str,
        *,
        title: str = "Gesprächsnotiz",
        tags: list[str] | None = None,
    ) -> MemoryItem:
        """Add a conversation note to local memory."""
        return self.add_item(
            kind="conversation_note",
            title=title,
            content=content,
            tags=tags or ["chat"],
        )

    def list_items(self, *, kind: MemoryKind | None = None) -> list[MemoryItem]:
        """List memory items, optionally filtered by kind."""
        items = self._read_document().items
        if kind is None:
            return items
        return [item for item in items if item.kind == kind]

    def update_item(
        self,
        item_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> MemoryItem:
        """Update an existing memory item."""
        document = self._read_document()
        for item in document.items:
            if item.id == item_id:
                if title is not None:
                    item.title = title
                if content is not None:
                    item.content = content
                if tags is not None:
                    item.tags = tags
                item.updated_at = utc_now()
                self._write_document(document)
                return item
        raise KeyError(f"Memory item not found: {item_id}")

    def _read_document(self) -> MemoryDocument:
        self.initialize()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return MemoryDocument.model_validate(data)

    def _write_document(self, document: MemoryDocument) -> None:
        payload = document.model_dump(mode="json")
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
