"""Dynamic Home Assistant entity and capability resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from kira.agent.models import (
    ActionType,
    AgentIntent,
    ConversationContext,
    MetricType,
    SelectionMode,
)
from kira.agent.normalization import normalize_text, text_tokens
from kira.homeassistant.analysis import EntityView
from kira.homeassistant.world_model import HomeAssistantWorldSnapshot

_DOMAIN_CAPABILITIES: dict[str, set[str]] = {
    "automation": {"trigger", "turn_on", "turn_off"},
    "climate": {"set_temperature", "turn_on", "turn_off"},
    "cover": {"open", "close", "stop"},
    "fan": {"turn_on", "turn_off", "toggle"},
    "input_boolean": {"turn_on", "turn_off", "toggle"},
    "light": {"turn_on", "turn_off", "toggle"},
    "lock": {"lock", "unlock"},
    "media_player": {"turn_on", "turn_off", "play", "pause", "stop"},
    "scene": {"activate"},
    "script": {"run", "turn_on", "turn_off"},
    "switch": {"turn_on", "turn_off", "toggle"},
}

_ACTION_DOMAINS: dict[ActionType, set[str]] = {
    ActionType.TURN_ON: {"fan", "input_boolean", "light", "media_player", "switch"},
    ActionType.TURN_OFF: {"fan", "input_boolean", "light", "media_player", "switch"},
    ActionType.TOGGLE: {"fan", "input_boolean", "light", "switch"},
    ActionType.ADJUST_BRIGHTNESS: {"light"},
    ActionType.SET_BRIGHTNESS: {"light"},
    ActionType.ADJUST_COLOR_TEMPERATURE: {"light"},
    ActionType.SET_COLOR_TEMPERATURE: {"light"},
    ActionType.SET_TEMPERATURE: {"climate"},
    ActionType.OPEN: {"cover"},
    ActionType.CLOSE: {"cover"},
    ActionType.LOCK: {"lock"},
    ActionType.UNLOCK: {"lock"},
    ActionType.PLAY: {"media_player"},
    ActionType.PAUSE: {"media_player"},
    ActionType.STOP: {"media_player"},
}

_METRIC_DEVICE_CLASSES: dict[MetricType, set[str]] = {
    MetricType.TEMPERATURE: {"temperature"},
    MetricType.HUMIDITY: {"humidity"},
    MetricType.BATTERY: {"battery"},
    MetricType.POWER: {"power"},
    MetricType.ENERGY: {"energy"},
    MetricType.VOLTAGE: {"voltage"},
    MetricType.CURRENT: {"current"},
    MetricType.PRESSURE: {"pressure"},
    MetricType.ILLUMINANCE: {"illuminance"},
    MetricType.AIR_QUALITY: {"aqi", "pm25", "carbon_dioxide"},
}

_METRIC_UNITS: dict[MetricType, tuple[str, ...]] = {
    MetricType.TEMPERATURE: ("c", "f", "grad"),
    MetricType.HUMIDITY: ("%",),
    MetricType.BATTERY: ("%",),
    MetricType.POWER: ("w", "kw"),
    MetricType.ENERGY: ("wh", "kwh"),
    MetricType.VOLTAGE: ("v",),
    MetricType.CURRENT: ("a", "ma"),
    MetricType.PRESSURE: ("hpa", "bar"),
    MetricType.ILLUMINANCE: ("lx",),
}

_SEMANTIC_TAGS: dict[str, tuple[str, ...]] = {
    "outside": (
        "aussen",
        "draussen",
        "outdoor",
        "garten",
        "balkon",
        "terrasse",
    ),
    "inside": ("innen", "drinnen", "indoor"),
    "main": ("haupt", "decke", "ceiling"),
    "indirect": ("indirekt", "ambient", "ambilight", "led", "tv wand"),
    "work": ("arbeit", "arbeitsplatz", "desk", "office", "pc"),
    "television": ("fernseher", "television", "tv"),
    "printer": ("drucker", "printer", "3d"),
    "door": ("tuer", "door"),
    "window": ("fenster", "window"),
}

_REFERENCE_WORDS = {
    "",
    "es",
    "das",
    "ihn",
    "ihm",
    "sie",
    "dort",
    "hier",
    "andere",
    "anderen",
    "wieder",
    "vorher",
    "genauso",
    "nochmal",
    "geraet",
    "licht",
    "lampe",
}

_GENERIC_TARGET_WORDS = {
    "das",
    "der",
    "die",
    "den",
    "ein",
    "eine",
    "im",
    "in",
    "auf",
    "vom",
    "von",
    "bitte",
    "mal",
    "geraet",
    "wert",
    "zustand",
}

_BROAD_TARGET_WORDS = {"alle", "alles", "geraet", "geraete", "komplett", "saemtliche"}
_OUTSIDE_TERMS = {"aussen", "draussen", "garten", "balkon", "terrasse", "outdoor"}
_OFFLINE_QUERY_DOMAINS = {
    "binary_sensor",
    "camera",
    "climate",
    "cover",
    "device_tracker",
    "fan",
    "humidifier",
    "light",
    "lock",
    "media_player",
    "sensor",
    "switch",
    "vacuum",
    "water_heater",
}
_OPENING_DEVICE_CLASSES = {"door", "garage_door", "opening", "window"}


@dataclass(frozen=True, slots=True)
class EntityDescriptor:
    """Rich internal representation of one Home Assistant entity."""

    entity_id: str
    name: str
    domain: str
    state: str
    room: str | None
    device_id: str | None
    device_name: str | None
    device_class: str | None
    unit: str | None
    available: bool
    capabilities: frozenset[str]
    tags: frozenset[str]
    attributes: dict[str, Any]
    related_entity_ids: tuple[str, ...] = ()

    @property
    def search_text(self) -> str:
        """Return normalized text used for entity matching."""
        values = [
            self.entity_id.replace(".", " ").replace("_", " "),
            self.name,
            self.room or "",
            self.device_name or "",
            self.device_class or "",
            " ".join(sorted(self.tags)),
        ]
        return normalize_text(" ".join(values))


@dataclass(frozen=True, slots=True)
class ScoredEntity:
    """Entity candidate with deterministic score evidence."""

    entity: EntityDescriptor
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityResolution:
    """Result of resolving an intent to current Home Assistant entities."""

    matches: tuple[EntityDescriptor, ...] = ()
    candidates: tuple[ScoredEntity, ...] = ()
    ambiguous: bool = False
    reason: str = ""


@dataclass(slots=True)
class EntityCatalog:
    """Current searchable catalog of Home Assistant entities."""

    entities: list[EntityDescriptor]
    by_id: dict[str, EntityDescriptor] = field(init=False)

    def __post_init__(self) -> None:
        """Build lookup indexes and device relationships."""
        grouped: dict[str, list[str]] = {}
        for entity in self.entities:
            if entity.device_id:
                grouped.setdefault(entity.device_id, []).append(entity.entity_id)
        with_relations = []
        for entity in self.entities:
            related = tuple(
                item
                for item in grouped.get(entity.device_id or "", [])
                if item != entity.entity_id
            )
            with_relations.append(
                EntityDescriptor(
                    entity_id=entity.entity_id,
                    name=entity.name,
                    domain=entity.domain,
                    state=entity.state,
                    room=entity.room,
                    device_id=entity.device_id,
                    device_name=entity.device_name,
                    device_class=entity.device_class,
                    unit=entity.unit,
                    available=entity.available,
                    capabilities=entity.capabilities,
                    tags=entity.tags,
                    attributes=entity.attributes,
                    related_entity_ids=related,
                )
            )
        self.entities = with_relations
        self.by_id = {entity.entity_id: entity for entity in self.entities}

    @classmethod
    def from_snapshot(cls, snapshot: HomeAssistantWorldSnapshot) -> EntityCatalog:
        """Build a catalog from a world-model snapshot."""
        return cls.from_entities(snapshot.entities)

    @classmethod
    def from_entities(cls, entities: list[EntityView]) -> EntityCatalog:
        """Build a catalog from normalized Home Assistant entities."""
        return cls([_descriptor(entity) for entity in entities])

    def model_context(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """Return a compact, bounded entity catalog for semantic interpretation."""
        prioritized = sorted(
            self.entities,
            key=lambda entity: (
                entity.domain not in {"scene", "script", "automation"},
                not entity.capabilities,
                not entity.available,
                entity.entity_id,
            ),
        )
        return [
            {
                "entity_id": entity.entity_id,
                "name": entity.name,
                "domain": entity.domain,
                "room": entity.room,
                "state": entity.state,
                "device_class": entity.device_class,
                "unit": entity.unit,
                "capabilities": sorted(entity.capabilities),
                "tags": sorted(entity.tags),
            }
            for entity in prioritized[:limit]
        ]


class EntityResolver:
    """Resolve semantic targets without trusting model-provided identifiers."""

    def resolve(
        self,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> EntityResolution:
        """Return validated current entities for an intent."""
        explicit_ids = _entity_ids(intent.target or "")
        if explicit_ids:
            matches = tuple(
                entity
                for entity_id in explicit_ids
                if (entity := catalog.by_id.get(entity_id)) is not None
                and (entity.available or self._includes_unavailable(intent))
                and self._matches_state_filter(intent, entity)
            )
            missing = sorted(set(explicit_ids) - set(catalog.by_id))
            if missing:
                return EntityResolution(
                    matches=matches,
                    reason=f"Unbekannte Entity: {', '.join(missing)}",
                )
            return EntityResolution(matches=matches, reason="explicit_entity_id")

        reference_matches = self._reference_matches(intent, context, catalog)
        if reference_matches:
            return EntityResolution(
                matches=tuple(reference_matches),
                reason="conversation_reference",
            )

        broad_matches = self._broad_query_matches(intent, context, catalog)
        if broad_matches:
            return EntityResolution(
                matches=tuple(broad_matches),
                reason="broad_query_selection",
            )

        broad_matches = self._broad_action_matches(intent, context, catalog)
        if broad_matches:
            return EntityResolution(
                matches=tuple(broad_matches),
                reason="broad_action_selection",
            )

        candidates = self._score(intent, context, catalog)
        if not candidates or candidates[0].score < 18:
            return EntityResolution(candidates=tuple(candidates[:5]), reason="no_match")

        selected, ambiguous = self._select(intent, candidates)
        return EntityResolution(
            matches=tuple(item.entity for item in selected),
            candidates=tuple(candidates[:10]),
            ambiguous=ambiguous,
            reason="ambiguous" if ambiguous else "scored_match",
        )

    def _broad_query_matches(
        self,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> list[EntityDescriptor]:
        if (
            intent.kind.value != "query"
            or intent.selection is not SelectionMode.ALL
            or not intent.state_filter
        ):
            return []
        domains = self._expected_domains(intent)
        if self._includes_unavailable(intent) and not domains:
            domains = set(_OFFLINE_QUERY_DOMAINS)
        if not domains and set(intent.state_filter) <= {
            "idle",
            "off",
            "on",
            "playing",
            "standby",
        }:
            domains = set(_ACTION_DOMAINS[ActionType.TURN_ON])
        room = normalize_text(intent.room or context.source_room or "")
        return [
            entity
            for entity in catalog.entities
            if (entity.available or self._includes_unavailable(intent))
            and (not domains or entity.domain in domains)
            and self._matches_semantic_domain(intent, entity)
            and (not room or room in entity.search_text)
            and self._matches_state_filter(intent, entity)
        ]

    def _broad_action_matches(
        self,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> list[EntityDescriptor]:
        if intent.selection is not SelectionMode.ALL or intent.kind.value != "action":
            return []
        target_tokens = text_tokens(intent.target or "")
        if target_tokens and not target_tokens <= _BROAD_TARGET_WORDS:
            return []
        domains = self._expected_domains(intent)
        room = normalize_text(intent.room or context.source_room or "")
        return [
            entity
            for entity in catalog.entities
            if entity.available
            and (not domains or entity.domain in domains)
            and (not room or room in entity.search_text)
        ]

    def _reference_matches(
        self,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> list[EntityDescriptor]:
        target_tokens = text_tokens(intent.target or "")
        if target_tokens & {"andere", "anderen"}:
            previous = [
                catalog.by_id[entity_id]
                for entity_id in context.previous_entities
                if entity_id in catalog.by_id
            ]
            domains = self._expected_domains(intent) or {
                entity.domain for entity in previous
            }
            room = normalize_text(
                intent.room or context.previous_room or context.source_room or ""
            )
            alternatives = [
                entity
                for entity in catalog.entities
                if entity.entity_id not in context.previous_entities
                and (entity.available or self._includes_unavailable(intent))
                and (not domains or entity.domain in domains)
                and (not room or room in entity.search_text)
                and self._matches_state_filter(intent, entity)
            ]
            if len(alternatives) == 1:
                return alternatives
            return []
        has_reference = bool(target_tokens & _REFERENCE_WORDS) or not target_tokens
        if not has_reference or not context.previous_entities:
            return []
        domains = self._expected_domains(intent)
        matches = [
            entity
            for entity_id in context.previous_entities
            if (entity := catalog.by_id.get(entity_id)) is not None
            and (entity.available or self._includes_unavailable(intent))
            and (not domains or entity.domain in domains)
            and self._matches_state_filter(intent, entity)
        ]
        room = normalize_text(intent.room or "")
        if room:
            matches = [entity for entity in matches if room in entity.search_text]
        return matches

    def _score(
        self,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> list[ScoredEntity]:
        target = normalize_text(intent.target or "")
        target_tokens = text_tokens(target) - _GENERIC_TARGET_WORDS
        room = normalize_text(intent.room or context.source_room or "")
        domains = self._expected_domains(intent)
        scored: list[ScoredEntity] = []
        for entity in catalog.entities:
            if not entity.available and not self._includes_unavailable(intent):
                continue
            if domains and entity.domain not in domains:
                continue
            if not self._matches_semantic_domain(intent, entity):
                continue
            if not self._matches_state_filter(intent, entity):
                continue
            score, reasons = self._score_entity(
                entity,
                intent=intent,
                target=target,
                target_tokens=target_tokens,
                room=room,
                context=context,
            )
            if score > 0:
                scored.append(ScoredEntity(entity, score, tuple(reasons)))
        return sorted(scored, key=lambda item: (-item.score, item.entity.entity_id))

    def _matches_state_filter(
        self,
        intent: AgentIntent,
        entity: EntityDescriptor,
    ) -> bool:
        if intent.selection is not SelectionMode.ALL or not intent.state_filter:
            return True
        allowed = {normalize_text(state) for state in intent.state_filter}
        return normalize_text(entity.state) in allowed

    def _includes_unavailable(self, intent: AgentIntent) -> bool:
        allowed = {normalize_text(state) for state in intent.state_filter}
        return bool(allowed & {"unavailable", "unknown"})

    def _matches_semantic_domain(
        self,
        intent: AgentIntent,
        entity: EntityDescriptor,
    ) -> bool:
        if normalize_text(intent.domain_hint or "") != "opening":
            return True
        request_words = text_tokens(f"{intent.goal} {intent.target or ''}")
        if "fenster" in request_words:
            return "window" in entity.tags
        if request_words & {"tuer", "tueren"}:
            return "door" in entity.tags
        return entity.domain == "cover" or (
            entity.domain == "binary_sensor"
            and normalize_text(entity.device_class or "") in _OPENING_DEVICE_CLASSES
        )

    def _score_entity(
        self,
        entity: EntityDescriptor,
        *,
        intent: AgentIntent,
        target: str,
        target_tokens: set[str],
        room: str,
        context: ConversationContext,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        haystack = entity.search_text
        if target and target in haystack:
            score += 24
            reasons.append("target_phrase")
        overlap = {token for token in target_tokens if token in haystack}
        if overlap:
            score += len(overlap) * 7
            reasons.append("target_tokens")
        if target and not overlap:
            similarity = SequenceMatcher(None, target, entity.name.lower()).ratio()
            if similarity >= 0.65:
                score += similarity * 12
                reasons.append("name_similarity")
        if room:
            normalized_room = normalize_text(entity.room or "")
            if normalized_room and (room in normalized_room or normalized_room in room):
                score += 32
                reasons.append("room")
            elif room in haystack:
                score += 20
                reasons.append("room_text")
        location_text = normalize_text(
            " ".join(value for value in (intent.goal, target, room) if value)
        )
        if any(term in location_text for term in _OUTSIDE_TERMS):
            if "outside" in entity.tags:
                score += 36
                reasons.append("outside_location")
            elif entity.domain != "weather":
                score -= 12
                reasons.append("not_outside")
        metric_score = self._metric_score(intent.metric, entity)
        if metric_score:
            score += metric_score
            reasons.append("metric")
        if intent.domain_hint and entity.domain == normalize_text(intent.domain_hint):
            score += 18
            reasons.append("domain")
        if entity.entity_id in context.previous_entities:
            score += 8
            reasons.append("recent_entity")
        if context.previous_room and normalize_text(context.previous_room) in haystack:
            score += 4
            reasons.append("recent_room")
        return score, reasons

    def _metric_score(
        self,
        metric: MetricType,
        entity: EntityDescriptor,
    ) -> float:
        if metric in {MetricType.NONE, MetricType.STATE}:
            return 0
        classes = _METRIC_DEVICE_CLASSES.get(metric, set())
        if normalize_text(entity.device_class or "") in classes:
            return 38
        metric_name = normalize_text(metric.value)
        if metric_name in entity.search_text:
            return 28
        normalized_unit = normalize_text(entity.unit or "")
        if normalized_unit in _METRIC_UNITS.get(metric, ()):
            return 14
        if entity.domain == "weather" and metric is MetricType.TEMPERATURE:
            return 8
        return 0

    def _expected_domains(self, intent: AgentIntent) -> set[str]:
        if normalize_text(intent.domain_hint or "") == "opening":
            return {"binary_sensor", "cover"}
        if intent.domain_hint:
            return {normalize_text(intent.domain_hint)}
        if intent.action in _ACTION_DOMAINS:
            return _ACTION_DOMAINS[intent.action]
        if intent.kind.value == "query" and intent.metric is not MetricType.STATE:
            return {"sensor", "binary_sensor", "weather", "climate"}
        return set()

    def _select(
        self,
        intent: AgentIntent,
        candidates: list[ScoredEntity],
    ) -> tuple[list[ScoredEntity], bool]:
        best = candidates[0]
        close = [
            candidate for candidate in candidates if best.score - candidate.score <= 3
        ]
        if intent.selection is SelectionMode.ALL:
            broad_matches = [
                candidate
                for candidate in candidates
                if best.score - candidate.score <= 12
            ]
            return broad_matches, False
        if intent.kind.value == "query":
            return close[:5], False
        if intent.selection is SelectionMode.SINGLE:
            return [best], len(close) > 1
        generic_target = text_tokens(intent.target or "") <= _REFERENCE_WORDS
        same_room_domain = bool(intent.room) and all(
            item.entity.room == close[0].entity.room
            and item.entity.domain == close[0].entity.domain
            for item in close
        )
        if len(close) > 1 and generic_target and same_room_domain:
            return close, False
        return [best], len(close) > 1


def _descriptor(entity: EntityView) -> EntityDescriptor:
    attributes = entity.raw.get("attributes", {})
    if not isinstance(attributes, dict):
        attributes = {}
    room = _first_text(attributes, "area_name", "area_id", "room") or entity.room
    device_id = _first_text(attributes, "device_id")
    device_name = _first_text(attributes, "device_name", "device")
    device_class = _first_text(attributes, "device_class")
    unit = _first_text(attributes, "unit_of_measurement")
    capabilities = set(_DOMAIN_CAPABILITIES.get(entity.domain, set()))
    if entity.domain == "light":
        if _supports_brightness(attributes):
            capabilities.add("brightness")
        if _supports_color_temperature(attributes):
            capabilities.add("color_temperature")
        if (
            attributes.get("rgb_color") is not None
            or attributes.get("hs_color") is not None
        ):
            capabilities.add("color")
    tags = _semantic_tags(
        " ".join(
            value
            for value in (
                entity.entity_id,
                entity.friendly_name,
                room or "",
                device_name or "",
                device_class or "",
            )
            if value
        )
    )
    return EntityDescriptor(
        entity_id=entity.entity_id,
        name=entity.label,
        domain=entity.domain,
        state=entity.state,
        room=room,
        device_id=device_id,
        device_name=device_name,
        device_class=device_class,
        unit=unit,
        available=entity.state not in {"unavailable", "unknown"},
        capabilities=frozenset(capabilities),
        tags=frozenset(tags),
        attributes=attributes,
    )


def _first_text(attributes: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = attributes.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _supports_brightness(attributes: dict[str, Any]) -> bool:
    supported = attributes.get("supported_features")
    color_modes = attributes.get("supported_color_modes")
    return bool(
        attributes.get("brightness") is not None
        or attributes.get("brightness_pct") is not None
        or (isinstance(supported, int) and supported & 1)
        or (
            isinstance(color_modes, list)
            and any(
                mode
                in {
                    "brightness",
                    "color_temp",
                    "hs",
                    "rgb",
                    "rgbw",
                    "rgbww",
                    "xy",
                }
                for mode in color_modes
            )
        )
    )


def _supports_color_temperature(attributes: dict[str, Any]) -> bool:
    color_modes = attributes.get("supported_color_modes")
    return bool(
        attributes.get("color_temp") is not None
        or attributes.get("color_temp_kelvin") is not None
        or attributes.get("min_color_temp_kelvin") is not None
        or (isinstance(color_modes, list) and "color_temp" in color_modes)
    )


def _semantic_tags(value: str) -> set[str]:
    normalized = normalize_text(value)
    tags = set()
    for tag, aliases in _SEMANTIC_TAGS.items():
        if any(normalize_text(alias) in normalized for alias in aliases):
            tags.add(tag)
    return tags


def _entity_ids(value: str) -> list[str]:
    return list(
        dict.fromkeys(re.findall(r"\b[a-z_]+\.[a-z0-9_]+\b", normalize_text(value)))
    )
