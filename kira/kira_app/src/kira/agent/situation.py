"""Build a compact semantic situation from a Home Assistant world snapshot."""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kira.agent.activities import Activity, ActivityRecognizer
from kira.agent.entities import EntityCatalog, EntityDescriptor
from kira.agent.models import AgentRequestContext
from kira.agent.normalization import normalize_text
from kira.homeassistant.world_model import HomeAssistantWorldSnapshot


class ConfidenceValue(BaseModel):
    """One inferred text value with provenance and evidence."""

    model_config = ConfigDict(extra="forbid")

    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    evidence: list[str] = Field(default_factory=list)


class SituationEntity(BaseModel):
    """Bounded entity view included in a semantic situation."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    name: str
    domain: str
    state: str
    room: str | None = None
    device_class: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    last_changed: str | None = None


class SituationContext(BaseModel):
    """Compact semantic description of the current environment."""

    model_config = ConfigDict(extra="forbid")

    updated_at: str
    user_home: bool | None = None
    presence_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    presence_evidence: list[str] = Field(default_factory=list)
    time_period: str
    active_room: ConfidenceValue | None = None
    activities: list[Activity] = Field(default_factory=list)
    lighting: dict[str, list[SituationEntity]] = Field(default_factory=dict)
    entertainment: list[SituationEntity] = Field(default_factory=list)
    computers: list[SituationEntity] = Field(default_factory=list)
    printing: list[SituationEntity] = Field(default_factory=list)
    cleaning: list[SituationEntity] = Field(default_factory=list)
    openings: list[SituationEntity] = Field(default_factory=list)
    locks: list[SituationEntity] = Field(default_factory=list)
    alarms: list[SituationEntity] = Field(default_factory=list)
    energy: list[SituationEntity] = Field(default_factory=list)
    unavailable: list[SituationEntity] = Field(default_factory=list)
    recent_events: list[str] = Field(default_factory=list)
    recent_goals: list[str] = Field(default_factory=list)

    def compact(self, *, category_limit: int = 12) -> dict[str, Any]:
        """Return a bounded JSON-safe context for intent and planning."""

        def entities(items: list[SituationEntity]) -> list[dict[str, Any]]:
            return [item.model_dump(mode="json") for item in items[:category_limit]]

        return {
            "updated_at": self.updated_at,
            "user_home": self.user_home,
            "presence_confidence": self.presence_confidence,
            "time_period": self.time_period,
            "active_room": (
                self.active_room.model_dump(mode="json")
                if self.active_room is not None
                else None
            ),
            "activities": [
                item.model_dump(mode="json") for item in self.activities[:6]
            ],
            "lighting": {
                room: entities(items)
                for room, items in list(self.lighting.items())[:10]
            },
            "entertainment": entities(self.entertainment),
            "computers": entities(self.computers),
            "printing": entities(self.printing),
            "cleaning": entities(self.cleaning),
            "openings": entities(self.openings),
            "locks": entities(self.locks),
            "alarms": entities(self.alarms),
            "energy": entities(self.energy),
            "unavailable": entities(self.unavailable),
            "recent_events": self.recent_events[-10:],
            "recent_goals": self.recent_goals[-5:],
        }


class SituationAnalyzer:
    """Derive semantic situation categories from current, filtered state data."""

    def __init__(
        self,
        activity_recognizer: ActivityRecognizer | None = None,
        *,
        timezone: tzinfo | None = None,
    ) -> None:
        """Initialize the separate activity recognizer."""
        self.activity_recognizer = activity_recognizer or ActivityRecognizer()
        self.timezone = timezone or datetime.now().astimezone().tzinfo

    def analyze(
        self,
        snapshot: HomeAssistantWorldSnapshot,
        catalog: EntityCatalog,
        request: AgentRequestContext,
        *,
        recent_goals: tuple[str, ...] = (),
    ) -> SituationContext:
        """Create one compact situation for the current request timestamp."""
        raw_by_id = {item.entity_id: item.raw for item in snapshot.entities}
        user_home, presence_confidence, presence_evidence = self._presence(
            catalog,
            request.user,
        )
        time_period = self._time_period(request.timestamp)
        active_room = self._active_room(catalog, request.source_room)
        situation = SituationContext(
            updated_at=snapshot.updated_at,
            user_home=user_home,
            presence_confidence=presence_confidence,
            presence_evidence=presence_evidence,
            time_period=time_period,
            active_room=active_room,
            recent_events=[event.summary for event in snapshot.last_events[-10:]],
            recent_goals=list(recent_goals[-5:]),
        )
        for entity in catalog.entities:
            view = self._view(entity, raw_by_id.get(entity.entity_id, {}))
            room = entity.room or "unassigned"
            if entity.domain == "light":
                situation.lighting.setdefault(room, []).append(view)
            if entity.domain == "media_player" and entity.state in {
                "on",
                "playing",
                "paused",
            }:
                situation.entertainment.append(view)
            if self._is_computer(entity) and entity.state in {
                "on",
                "active",
                "running",
                "home",
            }:
                situation.computers.append(view)
            if self._is_printer(entity) and self._is_relevant_printer_state(entity):
                situation.printing.append(view)
            if entity.domain == "vacuum" and entity.state not in {
                "off",
                "idle",
                "docked",
                "unavailable",
                "unknown",
            }:
                situation.cleaning.append(view)
            if self._is_opening(entity):
                situation.openings.append(view)
            if entity.domain == "lock":
                situation.locks.append(view)
            if entity.domain == "alarm_control_panel":
                situation.alarms.append(view)
            if self._is_energy(entity):
                situation.energy.append(view)
            if not entity.available:
                situation.unavailable.append(view)
        situation.activities = self.activity_recognizer.recognize(
            catalog,
            user_home=user_home,
            presence_confidence=presence_confidence,
            time_period=time_period,
            active_room=active_room.value if active_room is not None else None,
            active_room_confidence=(
                active_room.confidence if active_room is not None else 0.0
            ),
            active_room_source=(
                active_room.source if active_room is not None else None
            ),
            events=tuple(snapshot.last_events),
            recent_goals=recent_goals,
        )
        return situation

    def _presence(
        self,
        catalog: EntityCatalog,
        user: str | None,
    ) -> tuple[bool | None, float, list[str]]:
        candidates = [
            item
            for item in catalog.entities
            if item.domain in {"person", "device_tracker"} and item.available
        ]
        if user:
            user_text = normalize_text(user)
            if user_text not in {
                "api user",
                "default",
                "homeassistant",
                "local user",
                "unknown",
            }:
                user_matches = [
                    item
                    for item in candidates
                    if user_text in item.search_text
                    or normalize_text(str(item.attributes.get("user_id", "")))
                    == user_text
                ]
                if not user_matches:
                    return None, 0.0, ["request_user_not_resolved"]
                candidates = user_matches
        if not candidates:
            return None, 0.0, []
        states = [item.state for item in candidates]
        home_count = sum(state in {"home", "on"} for state in states)
        away_count = sum(state in {"not_home", "away", "off"} for state in states)
        if not home_count and not away_count:
            return None, 0.0, [f"{item.entity_id}={item.state}" for item in candidates]
        user_home = home_count >= away_count
        majority = max(home_count, away_count) / max(1, home_count + away_count)
        source_quality = (
            0.96 if any(item.domain == "person" for item in candidates) else 0.86
        )
        confidence = min(0.99, majority * source_quality)
        return (
            user_home,
            confidence,
            [f"{item.entity_id}={item.state}" for item in candidates[:6]],
        )

    def _active_room(
        self,
        catalog: EntityCatalog,
        source_room: str | None,
    ) -> ConfidenceValue | None:
        if source_room:
            return ConfidenceValue(
                value=source_room,
                confidence=0.99,
                source="assist_source",
                evidence=[f"source_room={source_room}"],
            )
        scores: dict[str, float] = {}
        evidence: dict[str, list[str]] = {}
        names: dict[str, str] = {}
        for entity in catalog.entities:
            if not entity.room or not entity.available:
                continue
            key = normalize_text(entity.room)
            names[key] = entity.room
            semantic = normalize_text(
                f"{entity.device_class or ''} {entity.search_text}"
            )
            increment = 0.0
            if (
                entity.domain == "binary_sensor"
                and entity.state == "on"
                and any(
                    term in semantic
                    for term in ("motion", "occupancy", "presence", "beweg", "praesenz")
                )
            ):
                increment = 4.0
            elif entity.domain == "media_player" and entity.state in {
                "on",
                "playing",
            }:
                increment = 2.0
            elif entity.domain == "light" and entity.state == "on":
                increment = 0.4
            elif entity.state in {"on", "active", "running"}:
                increment = 0.7
            if not increment:
                continue
            scores[key] = scores.get(key, 0.0) + increment
            evidence.setdefault(key, []).append(f"{entity.entity_id}={entity.state}")
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        key, score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = max(0.0, score - runner_up)
        confidence = min(0.94, 0.5 + score / 10 + margin / 10)
        return ConfidenceValue(
            value=names[key],
            confidence=confidence,
            source="state_evidence",
            evidence=evidence[key][:6],
        )

    def _view(
        self,
        entity: EntityDescriptor,
        raw: dict[str, Any],
    ) -> SituationEntity:
        selected_attributes = {
            key: entity.attributes[key]
            for key in (
                "brightness",
                "current_position",
                "device_class",
                "media_content_type",
                "media_title",
                "power",
                "temperature",
                "unit_of_measurement",
            )
            if key in entity.attributes
        }
        return SituationEntity(
            entity_id=entity.entity_id,
            name=entity.name,
            domain=entity.domain,
            state=entity.state,
            room=entity.room,
            device_class=entity.device_class,
            attributes=selected_attributes,
            last_changed=(
                str(raw.get("last_changed")) if raw.get("last_changed") else None
            ),
        )

    def _time_period(self, timestamp: datetime) -> str:
        hour = timestamp.astimezone(self.timezone).hour
        if 5 <= hour < 10:
            return "morning"
        if 10 <= hour < 18:
            return "day"
        if 18 <= hour < 23:
            return "evening"
        return "night"

    def _is_computer(self, entity: EntityDescriptor) -> bool:
        return "work" in entity.tags or any(
            term in entity.search_text
            for term in ("computer", "desktop", "rechner", "server", " pc ")
        )

    def _is_printer(self, entity: EntityDescriptor) -> bool:
        return "printer" in entity.tags or "printing_3d" in entity.used_for

    def _is_relevant_printer_state(self, entity: EntityDescriptor) -> bool:
        state = normalize_text(entity.state)
        return state not in {"off", "idle", "unknown", "unavailable", "standby"}

    def _is_opening(self, entity: EntityDescriptor) -> bool:
        return entity.domain == "cover" or (
            entity.domain == "binary_sensor"
            and entity.device_class in {"door", "garage_door", "opening", "window"}
        )

    def _is_energy(self, entity: EntityDescriptor) -> bool:
        return entity.domain == "sensor" and entity.device_class in {
            "battery",
            "current",
            "energy",
            "power",
            "voltage",
        }
