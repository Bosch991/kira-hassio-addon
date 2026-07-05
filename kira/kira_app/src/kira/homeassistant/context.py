"""Resolve Home Assistant Assist origin and room-specific targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kira.homeassistant.analysis import EntityView

ROOM_LIGHTS: dict[str, tuple[str, ...]] = {
    "kueche": (
        "light.kuchen_licht",
        "light.led_kuche",
        "light.kuche_spot_1",
        "light.kuche_spot_2",
    ),
    "esszimmer": ("light.esszimmer",),
    "wohnzimmer_tv": ("light.schlafzimmer_tv_wand",),
    "badezimmer": ("light.badezimmer_licht",),
    "kinderzimmer": ("light.kinderzimmer", "light.kinderzimmer_rgb"),
    "schlafzimmer": ("light.schlafzimmer",),
    "arbeit": ("light.arbeit", "light.dimmable_light_12", "light.dimmable_light_13"),
}

ROOM_MEDIA_PLAYERS: dict[str, tuple[str, ...]] = {
    "kueche": (),
    "esszimmer": (),
    "wohnzimmer_tv": (),
    "badezimmer": (),
    "kinderzimmer": (),
    "schlafzimmer": (),
    "arbeit": (),
}

ROOM_ALIASES: dict[str, tuple[str, ...]] = {
    "kueche": ("kueche", "kuche", "küche", "kuchen"),
    "esszimmer": ("esszimmer", "essen", "esstisch"),
    "wohnzimmer_tv": ("wohnzimmer tv", "tv wand", "schlafzimmer tv", "tv"),
    "badezimmer": ("badezimmer", "bad"),
    "kinderzimmer": ("kinderzimmer", "kinder", "kind"),
    "schlafzimmer": ("schlafzimmer", "bett"),
    "arbeit": ("arbeit", "buero", "büro", "arbeitszimmer", "office"),
}

ROOM_NAMES: dict[str, str] = {
    "kueche": "Kueche",
    "esszimmer": "Esszimmer",
    "wohnzimmer_tv": "Wohnzimmer",
    "badezimmer": "Badezimmer",
    "kinderzimmer": "Kinderzimmer",
    "schlafzimmer": "Schlafzimmer",
    "arbeit": "Buero",
}

LIGHT_WORDS = {"licht", "lichter", "lampe", "lampen", "beleuchtung"}
RGB_WORDS = {"rgb", "farbe", "bunt"}


@dataclass(frozen=True, slots=True)
class AssistOrigin:
    """Origin fields optionally sent by Home Assistant Assist."""

    device_id: str | None = None
    conversation_id: str | None = None
    agent_id: str | None = None
    area_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResolvedHomeAssistantContext:
    """Resolved Home Assistant room context."""

    area_id: str | None
    area_name: str | None
    light_entities: list[str]
    media_player_entities: list[str]


class HomeAssistantContextResolver:
    """Resolve room context and preferred Home Assistant entities."""

    def resolve(
        self,
        *,
        text: str,
        origin: AssistOrigin | None,
        entities: list[EntityView],
    ) -> ResolvedHomeAssistantContext | None:
        """Resolve context from explicit text first, then Assist origin."""
        room_id = self.room_from_text(text)
        if room_id is None and origin is not None:
            room_id = self.room_from_origin(origin)
        if room_id is None:
            return None
        return self.context_for_room(room_id, entities=entities, text=text)

    def room_from_text(self, text: str) -> str | None:
        """Return an explicit room id mentioned in text, if any."""
        normalized = self._normalize(text)
        for room_id, aliases in ROOM_ALIASES.items():
            if any(self._normalize(alias) in normalized for alias in aliases):
                return room_id
        return None

    def room_from_origin(self, origin: AssistOrigin) -> str | None:
        """Return a room id from Assist request origin fields, if possible."""
        values = [
            origin.area_id,
            self._metadata_value(origin.metadata, "area_id"),
            self._metadata_value(origin.metadata, "area_name"),
            self._metadata_value(origin.metadata, "room"),
            self._metadata_value(origin.metadata, "room_name"),
            self._metadata_value(origin.metadata, "device_area_id"),
            origin.device_id,
            origin.agent_id,
            origin.conversation_id,
        ]
        for value in values:
            if value is None:
                continue
            room_id = self._room_from_value(value)
            if room_id is not None:
                return room_id
        return None

    def context_for_room(
        self,
        room_id: str,
        *,
        entities: list[EntityView],
        text: str = "",
    ) -> ResolvedHomeAssistantContext:
        """Build preferred entities for a known room."""
        entity_map = {
            entity.entity_id: entity
            for entity in entities
            if entity.state not in {"unavailable", "unknown"}
        }
        light_ids = list(ROOM_LIGHTS.get(room_id, ()))
        if self._asks_for_rgb(text):
            light_ids = [
                entity_id
                for entity_id in light_ids
                if "rgb" in entity_id
                or "rgb" in self._entity_label(entity_map, entity_id)
            ]
        available_lights = [
            entity_id for entity_id in light_ids if entity_id in entity_map
        ]
        available_media_players = [
            entity_id
            for entity_id in ROOM_MEDIA_PLAYERS.get(room_id, ())
            if entity_id in entity_map
        ]
        return ResolvedHomeAssistantContext(
            area_id=room_id,
            area_name=ROOM_NAMES.get(room_id, room_id),
            light_entities=available_lights,
            media_player_entities=available_media_players,
        )

    def _metadata_value(self, metadata: dict[str, Any], key: str) -> str | None:
        value = metadata.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for nested_key in ("id", "name", "area_id", "area_name"):
                nested = value.get(nested_key)
                if isinstance(nested, str):
                    return nested
        return None

    def _room_from_value(self, value: str) -> str | None:
        normalized = self._normalize(value)
        for room_id, aliases in ROOM_ALIASES.items():
            candidates = (room_id, ROOM_NAMES.get(room_id, ""), *aliases)
            if any(
                self._normalize(candidate) in normalized for candidate in candidates
            ):
                return room_id
        return None

    def _asks_for_rgb(self, text: str) -> bool:
        words = set(self._normalize(text).split())
        return bool(words & RGB_WORDS)

    def _entity_label(self, entity_map: dict[str, EntityView], entity_id: str) -> str:
        entity = entity_map.get(entity_id)
        if entity is None:
            return ""
        return self._normalize(entity.label)

    def _normalize(self, text: str) -> str:
        return (
            text.lower()
            .strip()
            .replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
            .replace("Ã¤", "ae")
            .replace("Ã¶", "oe")
            .replace("Ã¼", "ue")
            .replace("ÃŸ", "ss")
        )
