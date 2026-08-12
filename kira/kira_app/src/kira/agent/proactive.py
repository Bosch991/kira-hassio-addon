"""Policy boundary for future proactive Kira observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from kira.agent.normalization import normalize_text
from kira.agent.situation import SituationContext, SituationEntity


class ProactiveMode(StrEnum):
    """Allowed behavior after Kira detects a relevant situation."""

    DETECT = "detect"
    SUGGEST = "suggest"
    EXECUTE = "execute"


@dataclass(frozen=True, slots=True)
class ProactiveSignal:
    """A detected condition without an implied side effect."""

    key: str
    summary: str
    suggested_intent: str | None = None
    entity_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProactiveDecision:
    """Policy result kept separate from actual planning and execution."""

    signal: ProactiveSignal
    notify: bool
    execute: bool
    reason: str


@dataclass(slots=True)
class ProactivePolicy:
    """Keep detection, suggestion, and execution explicitly separated."""

    mode: ProactiveMode = ProactiveMode.DETECT
    auto_execution_enabled: bool = False
    allowed_auto_intents: set[str] = field(default_factory=set)

    def decide(self, signal: ProactiveSignal) -> ProactiveDecision:
        """Return policy flags without executing anything."""
        if self.mode is ProactiveMode.DETECT:
            return ProactiveDecision(signal, False, False, "detection_only")
        if self.mode is ProactiveMode.SUGGEST:
            return ProactiveDecision(signal, True, False, "suggestion_only")
        if signal.confidence < 0.9:
            return ProactiveDecision(signal, True, False, "confidence_too_low")
        allowed = (
            self.auto_execution_enabled
            and signal.suggested_intent is not None
            and signal.suggested_intent in self.allowed_auto_intents
        )
        if allowed:
            return ProactiveDecision(signal, True, True, "explicitly_allowed")
        return ProactiveDecision(signal, True, False, "auto_execution_disabled")


class ProactiveEngine:
    """Detect explainable suggestions from semantic situations only."""

    def __init__(self, *, unattended_light_minutes: int = 45) -> None:
        """Initialize conservative detection thresholds."""
        self.unattended_light_minutes = max(5, unattended_light_minutes)

    def detect(
        self,
        situation: SituationContext,
        *,
        now: datetime | None = None,
    ) -> list[ProactiveSignal]:
        """Return observations without notifying or executing anything."""
        observed_at = now or datetime.now(UTC)
        signals = [
            *self._unattended_lights(situation, observed_at),
            *self._important_unavailable(situation),
            *self._night_openings(situation),
        ]
        return sorted(signals, key=lambda item: (-item.confidence, item.key))

    def _unattended_lights(
        self,
        situation: SituationContext,
        now: datetime,
    ) -> list[ProactiveSignal]:
        active_room = situation.active_room
        if active_room is None or active_room.confidence < 0.75:
            return []
        current_room = normalize_text(active_room.value)
        signals: list[ProactiveSignal] = []
        for room, lights in situation.lighting.items():
            if normalize_text(room) == current_room:
                continue
            for light in lights:
                if normalize_text(light.state) != "on":
                    continue
                age = _age_minutes(light.last_changed, now)
                if age is None or age < self.unattended_light_minutes:
                    continue
                confidence = min(
                    0.92,
                    0.76 + active_room.confidence * 0.1 + min(age, 180) / 3000,
                )
                signals.append(
                    ProactiveSignal(
                        key=f"unattended_light:{light.entity_id}",
                        summary=(
                            f"{light.name} ist seit etwa {round(age)} Minuten an, "
                            f"waehrend {active_room.value} als aktiver Raum gilt."
                        ),
                        suggested_intent="light.turn_off",
                        entity_ids=(light.entity_id,),
                        confidence=confidence,
                        reason="Licht lange an, Raum nicht als aktiv erkannt",
                        evidence=(
                            f"last_changed={light.last_changed}",
                            f"active_room={active_room.value}",
                            f"active_room_confidence={active_room.confidence:.2f}",
                        ),
                    )
                )
        return signals

    def _important_unavailable(
        self,
        situation: SituationContext,
    ) -> list[ProactiveSignal]:
        return [
            ProactiveSignal(
                key=f"important_unavailable:{entity.entity_id}",
                summary=f"{entity.name} ist {entity.state}.",
                entity_ids=(entity.entity_id,),
                confidence=0.96,
                reason="Wichtige Home-Assistant-Entity ist nicht erreichbar",
                evidence=(f"{entity.entity_id}={entity.state}",),
            )
            for entity in situation.unavailable
            if _is_important_unavailable(entity)
        ]

    def _night_openings(
        self,
        situation: SituationContext,
    ) -> list[ProactiveSignal]:
        if situation.time_period != "night" or situation.user_home is False:
            return []
        return [
            ProactiveSignal(
                key=f"opening_at_night:{entity.entity_id}",
                summary=f"{entity.name} ist nachts noch offen.",
                entity_ids=(entity.entity_id,),
                confidence=min(0.94, 0.82 + situation.presence_confidence * 0.1),
                reason="Oeffnung ist nachts offen",
                evidence=(
                    f"{entity.entity_id}={entity.state}",
                    f"presence_confidence={situation.presence_confidence:.2f}",
                ),
            )
            for entity in situation.openings
            if _is_open(entity)
        ]


def _age_minutes(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    try:
        changed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if changed.tzinfo is None:
        changed = changed.replace(tzinfo=UTC)
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return max(0.0, (current - changed).total_seconds() / 60)


def _is_open(entity: SituationEntity) -> bool:
    state = normalize_text(entity.state)
    if entity.domain == "cover":
        return state in {"open", "opening"}
    return state in {"on", "open"}


def _is_important_unavailable(entity: SituationEntity) -> bool:
    """Select core devices while excluding noisy helper/control entities."""
    if entity.domain in {"alarm_control_panel", "climate", "lock"}:
        return True
    if entity.device_class in {
        "carbon_monoxide",
        "gas",
        "moisture",
        "problem",
        "safety",
        "smoke",
    }:
        return True
    text = normalize_text(f"{entity.entity_id} {entity.name}")
    ignored = {
        "bitte nicht storen",
        "durchsagen",
        "einfrieren",
        "kommunikation",
        "nightlight",
        "reverse",
        "shuffle",
        "sync send",
        "wiederholen",
    }
    if any(term in text for term in ignored):
        return False
    important_terms = {
        "3d drucker",
        "alarm",
        "drucker",
        "heizung",
        "pumpe",
        "rauch",
        "server",
        "tablet",
        "tuer",
        "tv",
        "waschmaschine",
    }
    return entity.domain in {"media_player", "switch"} and any(
        term in text for term in important_terms
    )
