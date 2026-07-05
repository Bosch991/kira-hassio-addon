"""Data models for local memory."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

MemoryKind = Literal["conversation_note", "project_knowledge"]


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


class MemoryItem(BaseModel):
    """A single durable memory item."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: MemoryKind
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryDocument(BaseModel):
    """JSON document persisted by the memory store."""

    version: int = 1
    items: list[MemoryItem] = Field(default_factory=list)
