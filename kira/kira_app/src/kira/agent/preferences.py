"""Explicit long-term user preferences kept outside conversation context."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from kira.agent.models import utc_now
from kira.agent.normalization import normalize_text
from kira.agent.persistence import AtomicDocumentStore


class Preference(BaseModel):
    """One explicitly supplied long-term preference."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    user: str
    activity: str
    room: str | None = None
    values: dict[str, Any]
    source: str = "explicit"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PreferenceDocument(BaseModel):
    """Versioned preference storage document."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    preferences: list[Preference] = Field(default_factory=list)


class PreferenceStore:
    """Persist only explicit preferences; no implicit learning occurs here."""

    def __init__(self, path: Path) -> None:
        """Initialize the typed storage boundary."""
        self._store = AtomicDocumentStore(
            path,
            document_type=PreferenceDocument,
            empty_factory=PreferenceDocument,
        )

    @property
    def path(self) -> Path:
        """Return the underlying JSON path."""
        return self._store.path

    def initialize(self) -> None:
        """Create an empty preference document when missing."""
        self._store.initialize()

    def set_explicit(
        self,
        *,
        user: str | None,
        activity: str,
        values: dict[str, Any],
        room: str | None = None,
    ) -> Preference:
        """Create or replace an explicit preference for one scope."""
        owner = user or "default"
        normalized_activity = normalize_text(activity).replace(" ", "_")
        normalized_room = normalize_text(room) if room else None
        saved: Preference | None = None

        def mutate(document: PreferenceDocument) -> None:
            nonlocal saved
            existing = next(
                (
                    item
                    for item in document.preferences
                    if item.user == owner
                    and item.activity == normalized_activity
                    and normalize_text(item.room or "")
                    == normalize_text(normalized_room or "")
                ),
                None,
            )
            now = utc_now()
            if existing is None:
                saved = Preference(
                    user=owner,
                    activity=normalized_activity,
                    room=normalized_room,
                    values=dict(values),
                    created_at=now,
                    updated_at=now,
                )
                document.preferences.append(saved)
                return
            existing.values = dict(values)
            existing.updated_at = now
            existing.source = "explicit"
            existing.confidence = 1.0
            saved = existing.model_copy(deep=True)

        self._store.update(mutate)
        assert saved is not None
        return saved

    def list(
        self,
        *,
        user: str | None = None,
        activity: str | None = None,
        room: str | None = None,
    ) -> list[Preference]:
        """Return matching preferences, newest first."""
        owner = user or "default"
        normalized_activity = (
            normalize_text(activity).replace(" ", "_") if activity else None
        )
        normalized_room = normalize_text(room) if room else None
        matches = [
            item
            for item in self._store.read().preferences
            if item.user == owner
            and (normalized_activity is None or item.activity == normalized_activity)
            and (
                normalized_room is None
                or normalize_text(item.room or "") == normalized_room
            )
        ]
        return sorted(matches, key=lambda item: item.updated_at, reverse=True)

    def values_for(
        self,
        *,
        user: str | None,
        activity: str,
        room: str | None,
    ) -> dict[str, Any]:
        """Merge explicit preferences from general to room-specific scope."""
        preferences = self.list(user=user, activity=activity)
        result: dict[str, Any] = {}
        for preference in reversed(preferences):
            if preference.room is None:
                result.update(preference.values)
        if room:
            normalized_room = normalize_text(room)
            for preference in reversed(preferences):
                if normalize_text(preference.room or "") == normalized_room:
                    result.update(preference.values)
        return result
