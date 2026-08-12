"""Deterministic German parser for explicit conditional tasks."""

from __future__ import annotations

import re

from kira.agent.entities import EntityCatalog, EntityResolver
from kira.agent.intents import LocalIntentResolver
from kira.agent.models import (
    ActionType,
    AgentIntent,
    ConversationContext,
    IntentKind,
    MetricType,
    SelectionMode,
)
from kira.agent.normalization import normalize_text, text_tokens
from kira.agent.task_models import (
    TaskAction,
    TaskActionKind,
    TaskCondition,
    TaskConditionKind,
    TaskDraft,
    TaskParseResult,
    TaskTrigger,
)


class TaskParser:
    """Parse explicit conditional requests without asking a language model."""

    _CONDITIONAL = re.compile(
        r"^(?:wenn|sobald)\s+(.+?)(?:\s*,\s*|\s+dann\s+)(.+)$",
        re.IGNORECASE,
    )
    _PREFIX = re.compile(r"^(?:wenn|sobald)\s+", re.IGNORECASE)
    _ACTION_START = re.compile(
        r"\b(?:benachrichtige|entriegle|informiere|mach|mache|oeffne|sag|"
        r"schalte|schliesse|starte|verriegle)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        entity_resolver: EntityResolver,
        action_resolver: LocalIntentResolver | None = None,
    ) -> None:
        """Initialize deterministic entity and action resolution."""
        self.entity_resolver = entity_resolver
        self.action_resolver = action_resolver or LocalIntentResolver()

    def is_task_request(self, message: str) -> bool:
        """Return whether a message has an explicit conditional structure."""
        return self._PREFIX.match(normalize_text(message)) is not None

    def parse(
        self,
        message: str,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> TaskParseResult:
        """Parse a conditional request into a typed task draft."""
        parts = self._parts(message)
        if parts is None:
            return TaskParseResult(
                message=(
                    "Ich erkenne den Wenn-dann-Auftrag, aber nicht die Grenze "
                    "zwischen Ausloeser und Aktion. Bitte formuliere ihn genauer."
                )
            )
        trigger_text, action_text = parts
        trigger, conditions, evidence = self._trigger(
            trigger_text,
            context,
            catalog,
        )
        if trigger is None:
            return TaskParseResult(
                message=(
                    "Ich erkenne den Ausloeser noch nicht sicher genug. "
                    "Bitte nenne Zustand und Geraet genauer."
                )
            )
        action = self._action(action_text, context, catalog)
        if action is None:
            return TaskParseResult(
                message=(
                    "Ich erkenne die spaetere Aktion noch nicht sicher genug. "
                    "Bitte formuliere sie als klaren Schaltbefehl oder "
                    "Benachrichtigung."
                )
            )
        confidence = min(
            trigger.confidence,
            action.intent.confidence if action.intent is not None else 0.95,
        )
        return TaskParseResult(
            draft=TaskDraft(
                request_text=message.strip(),
                trigger=trigger,
                conditions=conditions,
                actions=[action],
                confidence=confidence,
                evidence=[*evidence, f"action={action.kind}"],
            )
        )

    def _parts(self, message: str) -> tuple[str, str] | None:
        """Split punctuated and speech-transcribed conditional requests."""
        stripped = message.strip(" .!?")
        match = self._CONDITIONAL.match(stripped)
        if match is not None:
            return tuple(normalize_text(part) for part in match.groups())
        normalized = normalize_text(stripped)
        remainder = self._PREFIX.sub("", normalized, count=1)
        boundary = self._ACTION_START.search(remainder)
        if boundary is None or boundary.start() < 3:
            return None
        trigger = remainder[: boundary.start()].strip()
        action = remainder[boundary.start() :].strip()
        return (trigger, action) if trigger and action else None

    def _trigger(
        self,
        text: str,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> tuple[TaskTrigger | None, list[TaskCondition], list[str]]:
        trigger_text, conditions = self._conditions(text, context, catalog)
        specification = self._trigger_specification(trigger_text, context)
        if specification is None:
            return None, conditions, []
        target, domains, from_states, to_states, confidence, source = specification
        intent = AgentIntent(
            kind=IntentKind.QUERY,
            goal=f"Task-Trigger: {trigger_text}",
            action=ActionType.QUERY_STATE,
            target=target,
            domain_hint=domains[0] if domains else None,
            metric=MetricType.STATE,
            selection=SelectionMode.SINGLE,
            confidence=confidence,
        )
        resolution = self.entity_resolver.resolve(intent, context, catalog)
        matches = [
            entity
            for entity in resolution.matches
            if not domains or entity.domain in domains
        ]
        entity_ids = [item.entity_id for item in matches]
        resolved_confidence = confidence if entity_ids else min(confidence, 0.54)
        return (
            TaskTrigger(
                target=target,
                entity_ids=entity_ids,
                from_states=from_states,
                to_states=to_states,
                description=trigger_text,
                confidence=resolved_confidence,
            ),
            conditions,
            [source, f"trigger_entities={','.join(entity_ids) or 'none'}"],
        )

    def _conditions(
        self,
        text: str,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> tuple[str, list[TaskCondition]]:
        darkness = re.search(r"\bund\s+(?:es\s+)?dunkel\s+ist\b", text)
        if darkness is None:
            return text, []
        trigger_text = text[: darkness.start()].strip()
        condition_intent = AgentIntent(
            kind=IntentKind.QUERY,
            goal="Dunkelheit pruefen",
            action=ActionType.QUERY_STATE,
            target="helligkeit lux",
            domain_hint="sensor",
            metric=MetricType.ILLUMINANCE,
            selection=SelectionMode.SINGLE,
            confidence=0.82,
        )
        resolution = self.entity_resolver.resolve(
            condition_intent,
            context,
            catalog,
        )
        return trigger_text, [
            TaskCondition(
                kind=TaskConditionKind.NUMERIC_BELOW,
                target="helligkeit lux",
                entity_ids=[item.entity_id for item in resolution.matches],
                maximum=20.0,
                description="Es ist dunkel (unter 20 Lux)",
            )
        ]

    def _trigger_specification(
        self,
        text: str,
        context: ConversationContext,
    ) -> tuple[str, tuple[str, ...], list[str], list[str], float, str] | None:
        tokens = text_tokens(text)
        if tokens & {"druck", "drucker", "printing", "print"} and tokens & {
            "fertig",
            "beendet",
            "abgeschlossen",
            "complete",
            "finished",
        }:
            return (
                "3d drucker druck status",
                ("sensor", "binary_sensor"),
                ["printing", "running"],
                ["finished", "complete", "completed", "success", "idle"],
                0.9,
                "recognized_trigger=printing_finished",
            )
        if "waschmaschine" in tokens and tokens & {
            "fertig",
            "beendet",
            "abgeschlossen",
        }:
            return (
                "waschmaschine status",
                ("sensor", "binary_sensor"),
                ["running", "washing"],
                ["finished", "complete", "completed", "idle", "off"],
                0.9,
                "recognized_trigger=washing_finished",
            )
        if tokens & {"fernseher", "tv"} and tokens & {
            "ausgeht",
            "aus",
            "ausgeschaltet",
        }:
            return (
                "fernseher tv",
                ("media_player",),
                ["on", "playing", "paused"],
                ["off", "idle", "standby"],
                0.92,
                "recognized_trigger=television_off",
            )
        if "hause" in tokens and tokens & {"komme", "ankomme", "zurueckkomme"}:
            return (
                context.user or "person",
                ("person", "device_tracker"),
                ["not_home", "away"],
                ["home"],
                0.88,
                "recognized_trigger=arrival",
            )
        if ("ich" in tokens and tokens & {"gehe", "weggehe", "verlasse"}) or (
            "haus" in tokens and "verlasse" in tokens
        ):
            return (
                context.user or "person",
                ("person", "device_tracker"),
                ["home"],
                ["not_home", "away"],
                0.88,
                "recognized_trigger=departure",
            )
        return self._generic_trigger(text)

    def _generic_trigger(
        self,
        text: str,
    ) -> tuple[str, tuple[str, ...], list[str], list[str], float, str] | None:
        state_aliases = {
            "angeht": "on",
            "eingeschaltet": "on",
            "ausgeht": "off",
            "ausgeschaltet": "off",
            "offen": "on",
            "geschlossen": "off",
            "unavailable": "unavailable",
            "nicht verfuegbar": "unavailable",
        }
        normalized = normalize_text(text)
        matched = next(
            (
                (alias, state)
                for alias, state in state_aliases.items()
                if alias in normalized
            ),
            None,
        )
        if matched is None:
            return None
        alias, state = matched
        target = normalized.replace(alias, " ")
        target = re.sub(r"\b(?:der|die|das|ist|wird)\b", " ", target)
        target = normalize_text(target)
        if not target:
            return None
        return (
            target,
            (),
            [],
            [state],
            0.72,
            "recognized_trigger=generic_state",
        )

    def _action(
        self,
        text: str,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> TaskAction | None:
        tokens = text_tokens(text)
        if (
            {"sag", "bescheid"} <= tokens
            or "benachrichtige" in tokens
            or "informiere" in tokens
        ):
            return TaskAction(
                kind=TaskActionKind.NOTIFY,
                notification_text=text.strip(),
            )
        intent = self.action_resolver.resolve(text, context, catalog)
        if intent.kind is not IntentKind.ACTION or intent.action is ActionType.NONE:
            return None
        return TaskAction(kind=TaskActionKind.HOME_ASSISTANT, intent=intent)
