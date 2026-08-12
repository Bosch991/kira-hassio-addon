"""Whole-house Home Assistant world model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from kira.homeassistant.analysis import EntityView, HomeAssistantAnalyzer
from kira.homeassistant.client import HomeAssistantClient
from kira.homeassistant.events import HomeAssistantEventStore, HomeAssistantLiveEvent
from kira.homeassistant.registry import (
    HomeAssistantRegistryAdapter,
    HomeAssistantRegistrySnapshot,
)


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
    registry: HomeAssistantRegistrySnapshot | None = None
    last_events: list[HomeAssistantLiveEvent] = field(default_factory=list)


class HomeAssistantWorldModel:
    """Regularly refreshable Home Assistant world model."""

    def __init__(
        self,
        *,
        client: HomeAssistantClient,
        event_store: HomeAssistantEventStore | None = None,
        registry_adapter: HomeAssistantRegistryAdapter | None = None,
    ) -> None:
        """Initialize the world model."""
        self.client = client
        self.event_store = event_store
        self.registry_adapter = registry_adapter
        self.analyzer = HomeAssistantAnalyzer()
        self.snapshot: HomeAssistantWorldSnapshot | None = None
        self.last_refresh_ok = False
        self.last_refresh_error: str | None = None
        self._lock = RLock()

    def refresh(self) -> HomeAssistantWorldSnapshot | None:
        """Refresh the world model from Home Assistant states."""
        with self._lock:
            result = self.client.states()
            if not result.ok or not isinstance(result.data, list):
                self.last_refresh_ok = False
                self.last_refresh_error = result.error or "Unerwartete States-Antwort."
                return self.snapshot
            states = [item for item in result.data if isinstance(item, dict)]
            self.snapshot = self.from_states(states)
            self.last_refresh_ok = True
            self.last_refresh_error = None
            return self.snapshot

    def from_states(self, states: list[dict[str, Any]]) -> HomeAssistantWorldSnapshot:
        """Build a world snapshot from state payloads."""
        registry = (
            self.registry_adapter.refresh()
            if self.registry_adapter is not None
            else None
        )
        enriched_states = (
            self.registry_adapter.enrich_states(states, snapshot=registry)
            if self.registry_adapter is not None
            else states
        )
        analysis = self.analyzer.analyze(enriched_states)
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
            registry=registry,
            last_events=last_events,
        )

    def current(self) -> HomeAssistantWorldSnapshot | None:
        """Return current snapshot, refreshing once if needed."""
        with self._lock:
            return self.snapshot or self.refresh()
