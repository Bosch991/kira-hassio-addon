"""Evidence-based recognition of activities in the current household context."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from kira.agent.entities import EntityCatalog, EntityDescriptor
from kira.agent.models import utc_now
from kira.agent.normalization import normalize_text
from kira.homeassistant.events import HomeAssistantLiveEvent


class ActivityType(StrEnum):
    """Activities Kira can currently describe."""

    SLEEPING = "sleeping"
    WORKING = "working"
    WATCHING_TV = "watching_tv"
    COOKING = "cooking"
    PRINTING_3D = "printing_3d"
    CLEANING = "cleaning"
    AWAY = "away"
    ARRIVING_HOME = "arriving_home"


class Activity(BaseModel):
    """One inferred activity with transparent confidence evidence."""

    model_config = ConfigDict(extra="forbid")

    type: ActivityType
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    room: str | None = None
    detected_at: str = Field(default_factory=lambda: utc_now().isoformat())


class ActivityRecognizer:
    """Recognize activities from multiple current and recent signals."""

    def recognize(
        self,
        catalog: EntityCatalog,
        *,
        user_home: bool | None,
        presence_confidence: float,
        time_period: str,
        active_room: str | None,
        active_room_confidence: float = 0.0,
        active_room_source: str | None = None,
        events: tuple[HomeAssistantLiveEvent, ...] = (),
        recent_goals: tuple[str, ...] = (),
    ) -> list[Activity]:
        """Return ranked activities without turning weak evidence into certainty."""
        activities: list[Activity] = []
        room_presence = self._room_presence(catalog)
        media = [
            item
            for item in catalog.entities
            if item.domain == "media_player"
            and item.available
            and item.state in {"on", "playing", "paused"}
        ]
        for entity in media:
            evidence = [f"{entity.entity_id}={entity.state}"]
            confidence = 0.55 if entity.state == "playing" else 0.45
            room = entity.room or active_room
            if room and room_presence.get(normalize_text(room)):
                evidence.append(f"presence:{room}=true")
                confidence += 0.32
            elif (
                room
                and active_room
                and active_room_source == "assist_source"
                and normalize_text(room) == normalize_text(active_room)
            ):
                evidence.append(f"active_room={active_room}")
                confidence += 0.2
            if "television" in entity.tags or "watching_tv" in entity.used_for:
                evidence.append("device_semantics=television")
                confidence += 0.08
            activities.append(
                Activity(
                    type=ActivityType.WATCHING_TV,
                    confidence=min(confidence, 0.97),
                    evidence=evidence,
                    room=room,
                )
            )

        work_devices = self._active_matching(catalog, tags={"work"})
        if work_devices:
            room = work_devices[0].room or active_room
            evidence = [f"{work_devices[0].entity_id}={work_devices[0].state}"]
            confidence = 0.5
            if room and room_presence.get(normalize_text(room)):
                evidence.append(f"presence:{room}=true")
                confidence += 0.3
            if time_period in {"morning", "day", "evening"}:
                evidence.append(f"time_period={time_period}")
                confidence += 0.08
            activities.append(
                Activity(
                    type=ActivityType.WORKING,
                    confidence=min(confidence, 0.92),
                    evidence=evidence,
                    room=room,
                )
            )

        printer_signals = [
            item
            for item in catalog.entities
            if ("printer" in item.tags or "printing_3d" in item.used_for)
            and item.available
            and normalize_text(item.state)
            in {"on", "printing", "running", "busy", "druckt"}
        ]
        if printer_signals:
            evidence = [
                f"{item.entity_id}={item.state}" for item in printer_signals[:3]
            ]
            confidence = 0.62
            if len(printer_signals) > 1:
                confidence += 0.2
                evidence.append("multiple_printer_signals")
            if self._event_matches(events, {"drucker", "printer", "3d"}):
                confidence += 0.1
                evidence.append("recent_printer_event")
            activities.append(
                Activity(
                    type=ActivityType.PRINTING_3D,
                    confidence=min(confidence, 0.95),
                    evidence=evidence,
                    room=printer_signals[0].room,
                )
            )

        vacuums = [
            item
            for item in catalog.entities
            if item.domain == "vacuum"
            and item.available
            and normalize_text(item.state) in {"cleaning", "on", "returning", "running"}
        ]
        if vacuums:
            evidence = [f"{vacuums[0].entity_id}={vacuums[0].state}"]
            confidence = 0.76
            if self._event_matches(events, {"vacuum", "reinigung", "cleaning"}):
                evidence.append("recent_cleaning_event")
                confidence += 0.12
            activities.append(
                Activity(
                    type=ActivityType.CLEANING,
                    confidence=min(confidence, 0.94),
                    evidence=evidence,
                    room=vacuums[0].room,
                )
            )

        kitchen_presence = next(
            (
                room
                for room, present in room_presence.items()
                if present and "kueche" in normalize_text(room)
            ),
            None,
        )
        cooking_devices = [
            item
            for item in catalog.entities
            if item.available
            and item.state in {"on", "heating", "cooking"}
            and any(
                term in item.search_text
                for term in ("herd", "ofen", "koch", "dunst", "kitchen")
            )
        ]
        if kitchen_presence and cooking_devices:
            activities.append(
                Activity(
                    type=ActivityType.COOKING,
                    confidence=0.88,
                    evidence=[
                        f"presence:{kitchen_presence}=true",
                        f"{cooking_devices[0].entity_id}={cooking_devices[0].state}",
                    ],
                    room=cooking_devices[0].room or kitchen_presence,
                )
            )

        if user_home is False and presence_confidence >= 0.7:
            activities.append(
                Activity(
                    type=ActivityType.AWAY,
                    confidence=min(0.98, presence_confidence),
                    evidence=[f"presence_home=false:{presence_confidence:.2f}"],
                )
            )
        if user_home and self._arrival_event(events):
            activities.append(
                Activity(
                    type=ActivityType.ARRIVING_HOME,
                    confidence=0.93,
                    evidence=["presence_home=true", "recent_arrival_event"],
                )
            )
        if (
            user_home
            and time_period == "night"
            and active_room
            and active_room_confidence >= 0.7
            and "schlaf" in normalize_text(active_room)
        ):
            activities.append(
                Activity(
                    type=ActivityType.SLEEPING,
                    confidence=min(
                        0.92,
                        0.62
                        + presence_confidence * 0.1
                        + active_room_confidence * 0.15,
                    ),
                    evidence=[
                        "presence_home=true",
                        "time_period=night",
                        f"active_room={active_room}",
                        f"active_room_confidence={active_room_confidence:.2f}",
                    ],
                    room=active_room,
                )
            )
        return sorted(
            self._add_goal_evidence(activities, recent_goals),
            key=lambda item: item.confidence,
            reverse=True,
        )

    def _add_goal_evidence(
        self,
        activities: list[Activity],
        recent_goals: tuple[str, ...],
    ) -> list[Activity]:
        """Use recent goals only to strengthen independently observed activity."""
        goal_activities = {
            "arrive_home": ActivityType.ARRIVING_HOME,
            "clean": ActivityType.CLEANING,
            "cook": ActivityType.COOKING,
            "go_to_sleep": ActivityType.SLEEPING,
            "leave_home": ActivityType.AWAY,
            "start_3d_printing": ActivityType.PRINTING_3D,
            "start_work": ActivityType.WORKING,
            "watch_movie": ActivityType.WATCHING_TV,
        }
        matched = {
            goal: goal_activities[goal]
            for goal in recent_goals
            if goal in goal_activities
        }
        return [
            (
                item.model_copy(
                    update={
                        "confidence": min(0.98, item.confidence + 0.08),
                        "evidence": [*item.evidence, f"recent_goal={goal}"],
                    }
                )
                if (
                    goal := next(
                        (key for key, kind in matched.items() if kind is item.type),
                        None,
                    )
                )
                is not None
                else item
            )
            for item in activities
        ]

    def _room_presence(self, catalog: EntityCatalog) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for entity in catalog.entities:
            if entity.domain != "binary_sensor" or not entity.room:
                continue
            semantic = normalize_text(
                f"{entity.device_class or ''} {entity.search_text}"
            )
            if not any(
                term in semantic
                for term in ("motion", "occupancy", "presence", "beweg", "praesenz")
            ):
                continue
            result[normalize_text(entity.room)] = entity.state in {
                "on",
                "home",
                "detected",
                "occupied",
            }
        return result

    def _active_matching(
        self,
        catalog: EntityCatalog,
        *,
        tags: set[str],
    ) -> list[EntityDescriptor]:
        return [
            item
            for item in catalog.entities
            if item.available
            and item.state in {"on", "playing", "active", "running"}
            and (set(item.tags) & tags or set(item.used_for) & tags)
        ]

    def _event_matches(
        self,
        events: tuple[HomeAssistantLiveEvent, ...],
        terms: set[str],
    ) -> bool:
        return any(
            any(term in normalize_text(event.summary) for term in terms)
            for event in events[-10:]
        )

    def _arrival_event(self, events: tuple[HomeAssistantLiveEvent, ...]) -> bool:
        return any(
            event.domain in {"person", "device_tracker"}
            and event.old_state in {"not_home", "away"}
            and event.new_state == "home"
            for event in events[-10:]
        )
