"""Whole-house Home Assistant world model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from kira.homeassistant.analysis import EntityView, HomeAssistantAnalyzer
from kira.homeassistant.client import HomeAssistantClient
from kira.homeassistant.events import HomeAssistantEventStore, HomeAssistantLiveEvent


@dataclass(frozen=True, slots=True)
class HomeAssistantWorldSnapshot:
    """Structured view of the current Home Assistant world."""

    updated_at: str
    entities: list[EntityView]
    rooms: dict[str, list[EntityView]]
    domains: dict[str, list[EntityView]]
    active_devices: list[EntityView]
    unavailable_devices: list[EntityView]
    important_sensors: list[EntityView]
    last_events: list[HomeAssistantLiveEvent] = field(default_factory=list)


class HomeAssistantWorldModel:
    """Regularly refreshable Home Assistant world model."""

    def __init__(
        self,
        *,
        client: HomeAssistantClient,
        event_store: HomeAssistantEventStore | None = None,
    ) -> None:
        """Initialize the world model."""
        self.client = client
        self.event_store = event_store
        self.analyzer = HomeAssistantAnalyzer()
        self.snapshot: HomeAssistantWorldSnapshot | None = None

    def refresh(self) -> HomeAssistantWorldSnapshot | None:
        """Refresh the world model from Home Assistant states."""
        result = self.client.states()
        if not result.ok or not isinstance(result.data, list):
            return self.snapshot
        states = [item for item in result.data if isinstance(item, dict)]
        self.snapshot = self.from_states(states)
        return self.snapshot

    def from_states(self, states: list[dict[str, Any]]) -> HomeAssistantWorldSnapshot:
        """Build a world snapshot from state payloads."""
        analysis = self.analyzer.analyze(states)
        rooms: dict[str, list[EntityView]] = {}
        for entity in analysis.entities:
            if entity.room is None:
                continue
            rooms.setdefault(entity.room, []).append(entity)
        last_events = (
            self.event_store.list_events(limit=20)
            if self.event_store is not None and self.event_store.path.exists()
            else []
        )
        return HomeAssistantWorldSnapshot(
            updated_at=datetime.now(UTC).isoformat(),
            entities=analysis.entities,
            rooms=rooms,
            domains=analysis.by_domain,
            active_devices=[*analysis.active_lights, *analysis.switched_on],
            unavailable_devices=[*analysis.unavailable, *analysis.unknown],
            important_sensors=analysis.important_sensors,
            last_events=last_events,
        )

    def current(self) -> HomeAssistantWorldSnapshot | None:
        """Return current snapshot, refreshing once if needed."""
        return self.snapshot or self.refresh()
