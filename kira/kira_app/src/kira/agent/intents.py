"""Semantic and local intent interpretation for the Kira agent."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from kira.agent.entities import EntityCatalog
from kira.agent.models import (
    ActionType,
    AgentIntent,
    ConversationContext,
    IntentKind,
    MetricType,
    SelectionMode,
)
from kira.agent.normalization import normalize_text, text_tokens

_ACTION_ALIASES: Mapping[ActionType, tuple[str, ...]] = {
    ActionType.TURN_ON: (
        "einschalten",
        "schalte an",
        "schalte ein",
        "mach an",
        "mache an",
        "anmachen",
        "starte",
    ),
    ActionType.TURN_OFF: (
        "ausschalten",
        "schalte aus",
        "mach aus",
        "mache aus",
        "ausmachen",
        "beenden",
    ),
    ActionType.ADJUST_BRIGHTNESS: (
        "heller",
        "dunkler",
        "mehr licht",
        "weniger licht",
    ),
    ActionType.ADJUST_COLOR_TEMPERATURE: (
        "waermer",
        "kaelter",
        "warmweisser",
        "kaltweisser",
    ),
    ActionType.OPEN: ("oeffnen", "mach auf", "aufmachen"),
    ActionType.CLOSE: ("schliessen", "mach zu", "zumachen"),
    ActionType.LOCK: ("abschliessen", "verriegeln", "verriegle", "schliesse ab"),
    ActionType.UNLOCK: (
        "aufschliessen",
        "entriegeln",
        "entriegle",
        "schliesse auf",
    ),
    ActionType.PLAY: ("abspielen", "weiterspielen"),
    ActionType.PAUSE: ("pausieren", "pause"),
    ActionType.STOP: ("stoppen", "stopp"),
}

_ACTION_PATTERNS: tuple[tuple[ActionType, str], ...] = (
    (
        ActionType.TURN_ON,
        r"\b(?:mach|mache|schalte|starte)\b.+\b(?:an|ein)\b$",
    ),
    (
        ActionType.TURN_OFF,
        r"\b(?:mach|mache|schalte)\b.+\baus\b$",
    ),
    (ActionType.OPEN, r"\b(?:mach|mache|oeffne)\b.+\bauf\b$"),
    (ActionType.CLOSE, r"\b(?:mach|mache|schliesse)\b.+\bzu\b$"),
)

_METRIC_ALIASES: Mapping[MetricType, tuple[str, ...]] = {
    MetricType.TEMPERATURE: ("temperatur", "wie warm", "wie kalt", "grad", "temp"),
    MetricType.HUMIDITY: (
        "luftfeuchtigkeit",
        "luftfeuchte",
        "feuchtigkeit",
        "wie feucht",
    ),
    MetricType.BATTERY: ("batterie", "akku", "ladestand"),
    MetricType.POWER: ("leistung", "watt", "aktuelle erzeugung", "stromverbrauch"),
    MetricType.ENERGY: ("energie", "kilowattstunden", "kwh", "tagesertrag"),
    MetricType.VOLTAGE: ("spannung", "volt"),
    MetricType.CURRENT: ("stromstaerke", "ampere"),
    MetricType.PRESSURE: ("luftdruck", "druck"),
    MetricType.ILLUMINANCE: ("helligkeit", "lux"),
    MetricType.AIR_QUALITY: ("luftqualitaet", "co2", "feinstaub", "aqi"),
}

_DOMAIN_ALIASES: Mapping[str, tuple[str, ...]] = {
    "light": ("licht", "lichter", "lampe", "lampen", "beleuchtung"),
    "switch": ("schalter", "steckdose", "switch"),
    "fan": ("luefter", "ventilator", "fan"),
    "media_player": ("fernseher", "tv", "musik", "lautsprecher", "radio"),
    "cover": ("rollladen", "rollo", "jalousie", "fenster", "garage", "tor"),
    "climate": ("heizung", "thermostat", "klima"),
    "lock": ("schloss", "haustuer", "tuer"),
}

_COMPOUND_DOMAIN_ALIASES = {
    "fenster",
    "fernseher",
    "heizung",
    "lampe",
    "lautsprecher",
    "licht",
    "rollladen",
    "schloss",
    "steckdose",
    "thermostat",
    "tuer",
}

_WORKFLOW_ALIASES: Mapping[str, tuple[str, ...]] = {
    "movie": ("film schauen", "filmabend", "kino", "fernsehen"),
    "sleep": ("schlafen gehen", "ins bett", "ich gehe schlafen", "gute nacht"),
    "leave_home": ("wohnung verlassen", "haus verlassen", "ich gehe weg"),
    "arrive_home": ("nach hause kommen", "bin zuhause", "bin wieder da"),
    "cooking": ("kochen", "ich will kochen"),
    "work": ("arbeiten", "arbeitsmodus", "ich muss arbeiten"),
    "work_end": ("fertig fuer heute", "feierabend", "arbeit beenden"),
    "printing": ("3d drucken", "druck starten", "etwas drucken"),
    "cleaning": ("putzen", "saubermachen", "reinigung"),
    "night": ("nachtmodus", "abendmodus"),
    "guests": ("besuch kommt", "gaestemodus", "wir bekommen besuch"),
    "away": ("abwesenheit", "urlaubsmodus"),
}

_CONFIRM_PHRASES = {
    "bestaetigen",
    "bestaetige",
    "ja ausfuehren",
    "ja mach das",
    "ja bitte",
    "mach das",
    "ausfuehren",
}

_EXPLICIT_CONFIRM_PHRASES = {"bestaetigen", "bestaetige", "ausfuehren"}

_CANCEL_PHRASES = {
    "abbrechen",
    "nicht ausfuehren",
    "nein",
    "vergiss es",
    "lass es",
}

_EXPLICIT_CANCEL_PHRASES = {"abbrechen", "nicht ausfuehren"}

_REPEAT_PHRASES = {"wieder", "nochmal", "genauso", "wie vorher"}

_QUERY_MARKERS = {
    "wie",
    "was",
    "welche",
    "welcher",
    "wieviel",
    "wie viel",
    "status",
    "zustand",
    "zeige",
    "ist",
    "sind",
}

_ALL_MARKERS = {"alle", "alles", "saemtliche", "komplett", "nur"}
_PLURAL_TARGET_WORDS = {
    "geraete",
    "lampen",
    "lichter",
    "schalter",
    "sensoren",
    "steckdosen",
    "tueren",
    "fenster",
}

_TARGET_STOP_WORDS = {
    "an",
    "aus",
    "bitte",
    "das",
    "den",
    "der",
    "die",
    "ein",
    "eine",
    "einen",
    "bisschen",
    "geschlossen",
    "mal",
    "jetzt",
    "etwas",
    "noch",
    "und",
    "dann",
    "mach",
    "mache",
    "schalte",
    "wie",
    "was",
    "welche",
    "welcher",
    "ist",
    "offen",
    "sind",
    "verriegelt",
    "es",
    "mir",
}

_INTERPRETER_PROMPT = """Du interpretierst deutsche Anfragen fuer einen lokalen
Home-Assistant-Agenten. Ermittle das Ziel, nicht nur einzelne Woerter.

Regeln:
- Gib ausschliesslich das vorgegebene strukturierte AgentIntent-Modell zurueck.
- Verwende keine Home-Assistant-Servicebezeichnung und erfinde keine Entity-ID.
- `target` ist eine kurze natuerliche Beschreibung des gemeinten Geraets.
- `room` ist der explizite oder kontextuell gemeinte Raum, sonst null.
- Bei lesenden Fenster-/Tuerfragen ist `domain_hint="opening"`, damit sowohl
  binary_sensor als auch cover beruecksichtigt werden.
- Folgewoerter wie es, das, dort, hier und genauso duerfen als target erhalten
  bleiben; die deterministische Schicht loest sie gegen den Kontext auf.
- Ein Messwert oder Zustand ist kind=query und action=query_state.
- `state_filter` enthaelt nur bei Listenfragen gewuenschte kanonische States,
  z. B. ["on", "playing"] fuer eingeschaltete Geraete oder
  ["unavailable", "unknown"] fuer nicht erreichbare Geraete. Bei einer
  Ja/Nein-Frage zu einer konkreten Entity bleibt die Liste leer.
- Eine direkte Zustandsaenderung ist kind=action.
- Ein Lebensablauf wie Filmabend, Schlafengehen oder Feierabend ist
  kind=workflow und bekommt einen knappen workflow-Schluessel.
- Bestaetigung und Abbruch gelten nur bei vorhandenem pending_plan.
- Freies Gespraech ohne Hausbezug ist kind=conversation.
- confidence bewertet nur die semantische Interpretation, nicht die technische
  Ausfuehrbarkeit.
"""


@dataclass(frozen=True, slots=True)
class IntentResolution:
    """Intent plus provenance and non-fatal semantic provider error."""

    intent: AgentIntent
    provider: str
    error: str | None = None


class IntentInterpreter(Protocol):
    """Boundary for semantic intent providers."""

    def interpret(
        self,
        message: str,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> AgentIntent | None:
        """Interpret one message as a structured intent."""


class OpenAIIntentInterpreter:
    """Use OpenAI Structured Outputs for semantic intent interpretation."""

    def __init__(self, api_key: str | None, model: str) -> None:
        """Initialize credentials and model selection."""
        self.api_key = api_key
        self.model = model
        self.logger = logging.getLogger(__name__)

    @property
    def is_configured(self) -> bool:
        """Return whether semantic interpretation can call OpenAI."""
        return bool(self.api_key)

    def interpret(
        self,
        message: str,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> AgentIntent | None:
        """Return a strictly parsed abstract intent or ``None`` on failure."""
        if not self.api_key:
            return None
        try:
            from openai import OpenAI  # type: ignore[import-not-found]

            response = OpenAI(api_key=self.api_key).responses.parse(
                model=self.model,
                instructions=_INTERPRETER_PROMPT,
                input=json.dumps(
                    self._payload(message, context, catalog),
                    ensure_ascii=False,
                ),
                text_format=AgentIntent,
                temperature=0,
            )
            parsed = response.output_parsed
            if isinstance(parsed, AgentIntent):
                return parsed
            return AgentIntent.model_validate(parsed) if parsed else None
        except Exception as exc:  # provider failures must preserve local operation
            self.logger.warning("Semantic intent interpretation failed: %s", exc)
            return None

    def _payload(
        self,
        message: str,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> dict[str, Any]:
        previous_intent = (
            context.previous_intent.model_dump(mode="json")
            if context.previous_intent is not None
            else None
        )
        return {
            "message": message,
            "context": {
                "source": context.source,
                "user": context.user,
                "source_device": context.source_device,
                "source_room": context.source_room,
                "timestamp": context.updated_at.isoformat(),
                "previous_room": context.previous_room,
                "previous_entities": context.previous_entities,
                "previous_intent": previous_intent,
                "has_pending_plan": context.pending_plan is not None,
                "has_pending_task": context.pending_task_id is not None,
            },
            "context_fusion": {
                key: value
                for key, value in catalog.semantic_context.items()
                if key != "relevant_entities"
            },
            "available_entities": catalog.semantic_context.get(
                "relevant_entities",
                catalog.model_context(),
            ),
        }


class LocalIntentResolver:
    """Small data-driven resolver for core intents and offline operation."""

    def __init__(
        self,
        workflow_aliases: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        """Initialize with optional workflow aliases from configuration."""
        aliases = workflow_aliases or _WORKFLOW_ALIASES
        self.workflow_aliases = {
            key: tuple(normalize_text(alias) for alias in values)
            for key, values in aliases.items()
        }

    def resolve(
        self,
        message: str,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> AgentIntent:
        """Interpret common requests without network access."""
        text = normalize_text(message).strip(" .!?")
        if text in _EXPLICIT_CONFIRM_PHRASES or (
            (context.pending_plan is not None or context.pending_task_id is not None)
            and text in _CONFIRM_PHRASES
        ):
            return AgentIntent(
                kind=IntentKind.CONFIRM,
                goal="Ausstehenden Plan bestaetigen",
                confidence=1.0,
                rationale="Explizite Bestaetigung",
            )
        if text in _EXPLICIT_CANCEL_PHRASES or (
            (context.pending_plan is not None or context.pending_task_id is not None)
            and text in _CANCEL_PHRASES
        ):
            return AgentIntent(
                kind=IntentKind.CANCEL,
                goal="Ausstehenden Plan abbrechen",
                confidence=1.0,
                rationale="Expliziter Abbruch",
            )
        if (
            context.previous_intent is not None
            and context.previous_intent.kind is IntentKind.ACTION
            and (
                text in _REPEAT_PHRASES
                or bool(
                    re.fullmatch(
                        r"(?:mach|mache)\s+(?:es|das)\s+(?:wieder|nochmal|genauso)",
                        text,
                    )
                )
            )
            and self._action(text) is ActionType.NONE
        ):
            return context.previous_intent.model_copy(
                update={
                    "goal": message.strip(),
                    "target": "es",
                    "room": context.previous_room,
                    "confidence": 0.75,
                    "rationale": "Vorherige Aktion referenziert",
                }
            )

        workflow = self._match_alias(text, self.workflow_aliases)
        if workflow is not None:
            return AgentIntent(
                kind=IntentKind.WORKFLOW,
                goal=message.strip(),
                workflow=workflow,
                room=self._room(text, catalog),
                confidence=0.84,
                rationale="Konfiguriertes Ablaufkonzept erkannt",
            )

        metric = self._match_enum_alias(text, _METRIC_ALIASES, MetricType.NONE)
        action = self._action(text)
        room = self._room(text, catalog)
        if "hier" in text_tokens(text) and context.source_room:
            room = context.source_room
        elif "dort" in text_tokens(text) and context.previous_room:
            room = context.previous_room
        domain = self._match_alias(text, _DOMAIN_ALIASES)
        words = text_tokens(text)
        selection = (
            SelectionMode.ALL
            if words & (_ALL_MARKERS | _PLURAL_TARGET_WORDS)
            else SelectionMode.AUTO
        )
        direction = self._direction(text)
        target = self._target(message, room)
        state_filter = self._state_filter(text)

        if (
            action is ActionType.NONE
            and metric is MetricType.NONE
            and context.previous_intent is not None
            and context.previous_intent.kind is IntentKind.QUERY
            and context.previous_intent.metric is not MetricType.NONE
            and room is not None
            and (words & {"und", "hier", "dort"} or len(words) <= 4)
        ):
            return context.previous_intent.model_copy(
                update={
                    "goal": message.strip(),
                    "target": context.previous_intent.metric.value,
                    "room": room,
                    "state_filter": [],
                    "confidence": 0.8,
                    "rationale": "Messwert-Folgefrage mit neuem Raum",
                }
            )

        if action is not ActionType.NONE:
            return AgentIntent(
                kind=IntentKind.ACTION,
                goal=message.strip(),
                action=action,
                target=target,
                room=room,
                domain_hint=domain,
                selection=selection,
                value=self._number(text),
                direction=direction,
                confidence=0.82,
                rationale="Lokale Aktionsgrammatik",
            )

        if (
            metric is not MetricType.NONE
            or state_filter
            or self._looks_like_state_query(text, catalog)
        ):
            return AgentIntent(
                kind=IntentKind.QUERY,
                goal=message.strip(),
                action=ActionType.QUERY_STATE,
                target=target,
                room=room,
                domain_hint=self._query_domain(domain, words),
                metric=metric if metric is not MetricType.NONE else MetricType.STATE,
                state_filter=state_filter,
                selection=selection,
                confidence=0.78,
                rationale="Lokale Zustandsabfrage",
            )

        return AgentIntent(
            kind=IntentKind.CONVERSATION,
            goal=message.strip(),
            confidence=0.4,
            rationale="Kein lokaler Home-Assistant-Intent erkannt",
        )

    def _match_alias(
        self,
        text: str,
        aliases: Mapping[str, Sequence[str]],
    ) -> str | None:
        matches = [
            (len(normalize_text(alias)), key)
            for key, values in aliases.items()
            for alias in values
            if _contains_phrase(text, normalize_text(alias))
        ]
        return max(matches)[1] if matches else None

    def _match_enum_alias(
        self,
        text: str,
        aliases: Mapping[Any, Sequence[str]],
        default: Any,
    ) -> Any:
        match = self._match_alias(
            text,
            {str(key): values for key, values in aliases.items()},
        )
        if match is None:
            return default
        enum_type = type(default)
        return enum_type(match)

    def _action(self, text: str) -> ActionType:
        action = self._match_enum_alias(text, _ACTION_ALIASES, ActionType.NONE)
        if action is not ActionType.NONE:
            return action
        for candidate, pattern in _ACTION_PATTERNS:
            if re.search(pattern, text):
                return candidate
        return ActionType.NONE

    def _room(self, text: str, catalog: EntityCatalog) -> str | None:
        rooms = {
            normalize_text(entity.room): entity.room
            for entity in catalog.entities
            if entity.room
        }
        for normalized, original in sorted(
            rooms.items(), key=lambda item: len(item[0]), reverse=True
        ):
            if normalized in text:
                return original
        outside_terms = {"aussen", "draussen", "garten", "balkon", "terrasse"}
        if text_tokens(text) & outside_terms:
            return "aussen"
        return None

    def _looks_like_state_query(self, text: str, catalog: EntityCatalog) -> bool:
        if not any(
            marker in text_tokens(text) or marker in text for marker in _QUERY_MARKERS
        ):
            return False
        text_words = text_tokens(text)
        if any(
            normalize_text(alias) in text_words
            for aliases in _DOMAIN_ALIASES.values()
            for alias in aliases
        ):
            return True
        if any(
            word.endswith(alias)
            for word in text_words
            for alias in _COMPOUND_DOMAIN_ALIASES
        ):
            return True
        tokens = text_words - _QUERY_MARKERS - _TARGET_STOP_WORDS
        return any(
            tokens & text_tokens(entity.search_text) for entity in catalog.entities
        )

    def _query_domain(self, domain: str | None, words: set[str]) -> str | None:
        if domain in {"cover", "lock"} and words & {"fenster", "tuer", "tueren"}:
            return "opening"
        return domain

    def _state_filter(self, text: str) -> list[str]:
        words = text_tokens(text)
        is_list_query = bool(
            words & {"welche", "welcher", "welchen"}
            or words & _PLURAL_TARGET_WORDS
            and "sind" in words
        )
        if not is_list_query:
            return []
        if "nicht verfuegbar" in text or words & {"offline", "unavailable"}:
            return ["unavailable", "unknown"]
        if words & {"eingeschaltet", "an"}:
            return ["on", "playing"]
        if words & {"ausgeschaltet", "aus"}:
            return ["off", "idle", "standby"]
        if "offen" in words:
            return ["on", "open", "opening"]
        if words & {"geschlossen", "zu"}:
            return ["off", "closed", "closing"]
        return []

    def _target(self, message: str, room: str | None) -> str:
        normalized = normalize_text(message)
        tokens = [
            token
            for token in normalized.split()
            if token not in _TARGET_STOP_WORDS
            and not (room and token in text_tokens(room))
            and not any(
                token in normalize_text(alias).split()
                for aliases in (*_ACTION_ALIASES.values(), *_METRIC_ALIASES.values())
                for alias in aliases
            )
        ]
        reference = text_tokens(normalized) & {"es", "das", "ihn", "dort", "hier"}
        if reference and not tokens:
            return sorted(reference)[0]
        return " ".join(tokens) or "es"

    def _number(self, text: str) -> float | None:
        match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(?:%|prozent|grad)?\b", text)
        return float(match.group(1).replace(",", ".")) if match else None

    def _direction(self, text: str) -> str | None:
        if "waermer" in text or "warmweisser" in text:
            return "warmer"
        if "kaelter" in text or "kaltweisser" in text:
            return "cooler"
        if any(term in text for term in ("dunkler", "weniger")):
            return "decrease"
        if any(term in text for term in ("heller", "mehr")):
            return "increase"
        return None


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))


class IntentResolver:
    """Use deterministic intents first and semantic interpretation when needed."""

    def __init__(
        self,
        *,
        semantic: IntentInterpreter | None = None,
        local: LocalIntentResolver | None = None,
    ) -> None:
        """Initialize resolver providers."""
        self.semantic = semantic
        self.local = local or LocalIntentResolver()

    def resolve(
        self,
        message: str,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> IntentResolution:
        """Resolve one message, using local interpretation on provider failure."""
        local_intent = self.local.resolve(message, context, catalog)
        if self._is_authoritative_local(message, local_intent):
            return IntentResolution(local_intent, "local")
        if self.semantic is not None:
            try:
                semantic_intent = self.semantic.interpret(message, context, catalog)
            except Exception as exc:  # custom providers must not break Kira
                return IntentResolution(local_intent, "local", str(exc))
            if semantic_intent is not None:
                return IntentResolution(
                    self._reconcile(semantic_intent, local_intent),
                    "semantic",
                )
        return IntentResolution(local_intent, "local")

    def _is_authoritative_local(
        self,
        message: str,
        intent: AgentIntent,
    ) -> bool:
        if intent.kind in {
            IntentKind.CANCEL,
            IntentKind.CONFIRM,
            IntentKind.QUERY,
            IntentKind.WORKFLOW,
        }:
            return True
        if intent.kind is not IntentKind.ACTION or intent.confidence < 0.75:
            return False
        if intent.action in {
            ActionType.ADJUST_BRIGHTNESS,
            ActionType.ADJUST_COLOR_TEMPERATURE,
        }:
            return True
        return "und" not in text_tokens(message)

    def _reconcile(
        self,
        semantic: AgentIntent,
        local: AgentIntent,
    ) -> AgentIntent:
        if semantic.kind is not local.kind:
            return semantic
        updates: dict[str, Any] = {}
        if local.room:
            updates["room"] = local.room
        if local.domain_hint:
            updates["domain_hint"] = local.domain_hint
        if local.selection is SelectionMode.ALL:
            updates["selection"] = SelectionMode.ALL
        if local.direction:
            updates["direction"] = local.direction
        if local.value is not None:
            updates["value"] = local.value
        if local.state_filter:
            updates["state_filter"] = local.state_filter
        if local.metric is not MetricType.NONE:
            updates["metric"] = local.metric
        return semantic.model_copy(update=updates) if updates else semantic
