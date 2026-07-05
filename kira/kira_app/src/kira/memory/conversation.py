"""Persistent conversation history for Kira."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ConversationRole = Literal["user", "assistant"]


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


class ConversationMessage(BaseModel):
    """A single persisted chat message."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    role: ConversationRole
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class ConversationDocument(BaseModel):
    """JSON document for persisted conversation history."""

    version: int = 1
    messages: list[ConversationMessage] = Field(default_factory=list)


@dataclass(slots=True)
class ConversationStore:
    """Store and load the most recent conversation messages."""

    path: Path
    max_messages: int = 20

    def initialize(self) -> None:
        """Create the conversation file when needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_document(ConversationDocument())

    def append(self, *, role: ConversationRole, content: str) -> ConversationMessage:
        """Append a message and trim history to the configured limit."""
        document = self._read_document()
        message = ConversationMessage(role=role, content=content)
        document.messages.append(message)
        document.messages = document.messages[-self.max_messages :]
        self._write_document(document)
        return message

    def recent(self) -> list[ConversationMessage]:
        """Return the persisted recent conversation messages."""
        return self._read_document().messages[-self.max_messages :]

    def count(self) -> int:
        """Return the number of persisted messages."""
        return len(self._read_document().messages)

    def _read_document(self) -> ConversationDocument:
        self.initialize()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return ConversationDocument.model_validate(data)

    def _write_document(self, document: ConversationDocument) -> None:
        payload = document.model_dump(mode="json")
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
