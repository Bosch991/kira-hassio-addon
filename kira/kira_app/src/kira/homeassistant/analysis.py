"""Home Assistant entity analysis and export helpers."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class EntityView:
    """Normalized Home Assistant entity view."""

    entity_id: str
    domain: str
    state: str
    friendly_name: str
    room: str | None
    raw: dict[str, Any]

    @property
    def label(self) -> str:
        """Return a human-friendly entity label."""
        return self.friendly_name or self.entity_id


@dataclass(frozen=True, slots=True)
class HomeAssistantAnalysis:
    """Computed Home Assistant analysis."""

    entities: list[EntityView]
    by_domain: dict[str, list[EntityView]]
    unavailable: list[EntityView]
    unknown: list[EntityView]
    active_lights: list[EntityView]
    switched_on: list[EntityView]
    important_sensors: list[EntityView]


@dataclass(frozen=True, slots=True)
class HomeAssistantExport:
    """Paths written by an export operation."""

    json_path: Path
    markdown_path: Path


ROOM_ALIASES = {
    "arbeitszimmer": ("arbeitszimmer", "buero", "büro", "office", "desk"),
    "bad": ("bad", "bath", "bathroom"),
    "flur": ("flur", "hall", "diele"),
    "garage": ("garage",),
    "keller": ("keller", "basement"),
    "kinderzimmer": ("kinderzimmer", "kind", "kids"),
    "küche": ("küche", "kueche", "kuche", "kitchen"),
    "schlafzimmer": ("schlafzimmer", "bedroom"),
    "wohnzimmer": ("wohnzimmer", "living", "livingroom", "sofa"),
}

IMPORTANT_SENSOR_TERMS = (
    "battery",
    "batterie",
    "energy",
    "energie",
    "feuchtigkeit",
    "humidity",
    "leistung",
    "power",
    "strom",
    "temperature",
    "temperatur",
    "verbrauch",
    "voltage",
)


class HomeAssistantAnalyzer:
    """Analyze Home Assistant state payloads."""

    def analyze(self, states: list[dict[str, Any]]) -> HomeAssistantAnalysis:
        """Analyze raw Home Assistant states."""
        entities = [self._entity_from_state(item) for item in states]
        by_domain: dict[str, list[EntityView]] = defaultdict(list)
        for entity in entities:
            by_domain[entity.domain].append(entity)

        unavailable = [entity for entity in entities if entity.state == "unavailable"]
        unknown = [entity for entity in entities if entity.state == "unknown"]
        active_lights = [
            entity
            for entity in entities
            if entity.domain == "light" and entity.state == "on"
        ]
        switched_on = [
            entity
            for entity in entities
            if entity.state == "on" and entity.domain not in {"light", "sensor"}
        ]
        important_sensors = [
            entity
            for entity in entities
            if entity.domain == "sensor" and self._is_important_sensor(entity)
        ]

        return HomeAssistantAnalysis(
            entities=entities,
            by_domain=dict(sorted(by_domain.items())),
            unavailable=unavailable,
            unknown=unknown,
            active_lights=active_lights,
            switched_on=switched_on,
            important_sensors=important_sensors,
        )

    def find(self, analysis: HomeAssistantAnalysis, text: str) -> list[EntityView]:
        """Find entities by entity id, friendly name, room, state, or domain."""
        needles = self._search_needles(text)
        if not needles:
            return []
        return [
            entity
            for entity in analysis.entities
            if self._matches_any_needle(entity, needles)
        ]

    def by_room(
        self,
        analysis: HomeAssistantAnalysis,
        room_name: str,
    ) -> list[EntityView]:
        """Return entities that roughly belong to a room."""
        room = self._detect_room(room_name)
        needle = self._normalize(room_name)
        return [
            entity
            for entity in analysis.entities
            if entity.room == room
            or needle in self._normalize(entity.entity_id)
            or needle in self._normalize(entity.friendly_name)
        ]

    def export(
        self,
        analysis: HomeAssistantAnalysis,
        output_dir: Path,
    ) -> HomeAssistantExport:
        """Export entities as JSON and Markdown."""
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "entities.json"
        markdown_path = output_dir / "entities.md"

        json_payload = [
            {
                "entity_id": entity.entity_id,
                "domain": entity.domain,
                "state": entity.state,
                "friendly_name": entity.friendly_name,
                "room": entity.room,
                "attributes": entity.raw.get("attributes", {}),
            }
            for entity in analysis.entities
        ]
        json_path.write_text(
            json.dumps(json_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        markdown_path.write_text(self.to_markdown(analysis), encoding="utf-8")
        return HomeAssistantExport(json_path=json_path, markdown_path=markdown_path)

    def to_markdown(self, analysis: HomeAssistantAnalysis) -> str:
        """Render a Markdown overview for an analysis."""
        lines = [
            "# Home Assistant Entities",
            "",
            f"- Entitäten: {len(analysis.entities)}",
            f"- Aktive Lichter: {len(analysis.active_lights)}",
            f"- Eingeschaltete Geräte: {len(analysis.switched_on)}",
            f"- Unavailable: {len(analysis.unavailable)}",
            f"- Unknown: {len(analysis.unknown)}",
            "",
        ]
        for domain, entities in analysis.by_domain.items():
            lines.append(f"## {domain}")
            for entity in entities:
                room = f" [{entity.room}]" if entity.room else ""
                lines.append(f"- `{entity.entity_id}`{room}: {entity.state}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _entity_from_state(self, item: dict[str, Any]) -> EntityView:
        entity_id = str(item.get("entity_id", "unknown.unknown"))
        domain = entity_id.split(".", maxsplit=1)[0]
        attributes = item.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}
        friendly_name = str(attributes.get("friendly_name", entity_id))
        state = str(item.get("state", "unknown"))
        return EntityView(
            entity_id=entity_id,
            domain=domain,
            state=state,
            friendly_name=friendly_name,
            room=self._detect_room(f"{entity_id} {friendly_name}"),
            raw=item,
        )

    def _is_important_sensor(self, entity: EntityView) -> bool:
        haystack = self._normalize(f"{entity.entity_id} {entity.friendly_name}")
        return any(term in haystack for term in IMPORTANT_SENSOR_TERMS)

    def _detect_room(self, text: str) -> str | None:
        haystack = self._normalize(text)
        for room, aliases in ROOM_ALIASES.items():
            if any(alias in haystack for alias in aliases):
                return room
        return None

    def _normalize(self, text: str) -> str:
        return (
            text.lower()
            .strip()
            .strip("<>")
            .replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )

    def _search_needles(self, text: str) -> list[str]:
        needle = self._normalize(text)
        if not needle:
            return []

        aliases = {
            "licht": ["licht", "light", "lampe"],
            "lichter": ["lichter", "licht", "light", "lampe", "lampen"],
            "lampe": ["lampe", "light", "licht"],
            "lampen": ["lampen", "lampe", "light", "licht"],
            "schalter": ["schalter", "switch"],
            "steckdose": ["steckdose", "switch"],
            "sensoren": ["sensoren", "sensor"],
        }
        return aliases.get(needle, [needle])

    def _matches_any_needle(self, entity: EntityView, needles: list[str]) -> bool:
        haystacks = [
            self._normalize(entity.entity_id),
            self._normalize(entity.friendly_name),
            self._normalize(entity.state),
            self._normalize(entity.domain),
        ]
        if entity.room is not None:
            haystacks.append(self._normalize(entity.room))
        return any(needle in haystack for needle in needles for haystack in haystacks)
