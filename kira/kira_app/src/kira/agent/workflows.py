"""Data-driven workflow concepts for context-aware Home Assistant plans."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kira.agent.entities import EntityCatalog, EntityDescriptor, EntityResolver
from kira.agent.models import (
    ActionPlan,
    ActionType,
    AgentIntent,
    ConversationContext,
    IntentKind,
    PlanStep,
    SelectionMode,
)
from kira.agent.normalization import normalize_text


class WorkflowStepDefinition(BaseModel):
    """One selector-driven fallback workflow step."""

    model_config = ConfigDict(extra="forbid")

    action: ActionType
    target: str
    domains: list[str] = Field(default_factory=list)
    room: str | None = None
    selection: SelectionMode = SelectionMode.AUTO
    states: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False


class WorkflowDefinition(BaseModel):
    """Named household concept and its Home Assistant preferences."""

    model_config = ConfigDict(extra="forbid")

    name: str
    aliases: list[str] = Field(default_factory=list)
    preferred_ha_terms: list[str] = Field(default_factory=list)
    fallback_steps: list[WorkflowStepDefinition] = Field(default_factory=list)


class WorkflowDocument(BaseModel):
    """Versioned workflow configuration document."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    workflows: dict[str, WorkflowDefinition] = Field(default_factory=dict)


class WorkflowPlanningResult(BaseModel):
    """Plan or a user-facing reason why no safe plan exists."""

    model_config = ConfigDict(extra="forbid")

    plan: ActionPlan | None = None
    matched_entity_ids: list[str] = Field(default_factory=list)
    message: str = ""


class WorkflowEngine:
    """Prefer existing HA workflows, then build configured fallback plans."""

    def __init__(self, path: Path, *, entity_resolver: EntityResolver) -> None:
        """Initialize workflow configuration and entity resolver."""
        self.path = path
        self.entity_resolver = entity_resolver
        self.document = WorkflowDocument()
        self.logger = logging.getLogger(__name__)
        self.reload()

    def reload(self) -> None:
        """Reload workflow definitions from disk."""
        if not self.path.exists():
            self.document = WorkflowDocument()
            return
        try:
            payload = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            document = WorkflowDocument.model_validate(payload)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            self.logger.warning("Agent workflows could not be reloaded: %s", exc)
            return
        self.document = document

    @property
    def aliases(self) -> dict[str, tuple[str, ...]]:
        """Expose workflow aliases to the local intent resolver."""
        return {
            key: tuple(definition.aliases)
            for key, definition in self.document.workflows.items()
        }

    def plan(
        self,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> WorkflowPlanningResult:
        """Build a workflow plan from current entities and states."""
        workflow_key = intent.workflow or self._workflow_from_goal(intent.goal)
        definition = self.document.workflows.get(workflow_key or "")
        if definition is None:
            return WorkflowPlanningResult(
                message="Diesen Ablauf kenne ich noch nicht sicher genug."
            )

        existing = self._existing_workflow(definition, intent, catalog)
        if existing is not None:
            step = self._existing_workflow_step(existing, definition)
            return WorkflowPlanningResult(
                plan=ActionPlan(
                    goal=intent.goal or definition.name,
                    intent=f"workflow.{workflow_key}",
                    steps=[step],
                    explanation=(
                        f"Vorhandenen Home-Assistant-Ablauf {existing.name} verwenden."
                    ),
                ),
                matched_entity_ids=[existing.entity_id],
            )

        steps: list[PlanStep] = []
        matched_ids: list[str] = []
        missing_required: list[str] = []
        for fallback in definition.fallback_steps:
            step_intent = self._step_intent(fallback, intent, context)
            resolution = self.entity_resolver.resolve(step_intent, context, catalog)
            matches = [
                entity
                for entity in resolution.matches
                if entity.domain in fallback.domains
                and (not fallback.states or entity.state in fallback.states)
                and _supports_data(entity, fallback.data)
            ]
            if not matches:
                if not fallback.optional:
                    missing_required.append(fallback.target)
                continue
            for domain in fallback.domains:
                domain_matches = [
                    entity for entity in matches if entity.domain == domain
                ]
                step = _plan_step(
                    step_intent,
                    domain_matches,
                    fallback.data,
                    definition.name,
                )
                if step is not None:
                    steps.append(step)
                    matched_ids.extend(entity.entity_id for entity in domain_matches)

        if missing_required:
            return WorkflowPlanningResult(
                message=(
                    "Fuer diesen Ablauf fehlt mir ein erreichbares Geraet: "
                    f"{', '.join(missing_required)}."
                )
            )
        if not steps:
            return WorkflowPlanningResult(
                message=(
                    f"Ich kenne den Ablauf {definition.name}, finde aber weder eine "
                    "passende Home-Assistant-Szene noch sichere dynamische Schritte."
                )
            )

        return WorkflowPlanningResult(
            plan=ActionPlan(
                goal=intent.goal or definition.name,
                intent=f"workflow.{workflow_key}",
                steps=steps,
                explanation=(
                    f"{definition.name} dynamisch aus dem aktuellen Hauszustand planen."
                ),
            ),
            matched_entity_ids=list(dict.fromkeys(matched_ids)),
        )

    def _workflow_from_goal(self, goal: str) -> str | None:
        text = normalize_text(goal)
        matches = [
            (len(normalize_text(alias)), key)
            for key, definition in self.document.workflows.items()
            for alias in definition.aliases
            if normalize_text(alias) in text
        ]
        return max(matches)[1] if matches else None

    def _existing_workflow(
        self,
        definition: WorkflowDefinition,
        intent: AgentIntent,
        catalog: EntityCatalog,
    ) -> EntityDescriptor | None:
        candidates: list[tuple[int, int, EntityDescriptor]] = []
        terms = {
            normalize_text(term)
            for term in [*definition.preferred_ha_terms, *definition.aliases]
            if term
        }
        room = normalize_text(intent.room or "")
        domain_order = {"scene": 0, "script": 1, "automation": 2}
        for entity in catalog.entities:
            if entity.domain not in domain_order or not entity.available:
                continue
            haystack = entity.search_text
            score = sum(len(term) for term in terms if term and term in haystack)
            if room and room in haystack:
                score += 20
            if score:
                candidates.append((score, -domain_order[entity.domain], entity))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], item[1]))[2]

    def _existing_workflow_step(
        self,
        entity: EntityDescriptor,
        definition: WorkflowDefinition,
    ) -> PlanStep:
        service = "trigger" if entity.domain == "automation" else "turn_on"
        return PlanStep(
            domain=entity.domain,
            service=service,
            entity_ids=[entity.entity_id],
            reason=f"Vorhandenen Ablauf {definition.name} verwenden",
        )

    def _step_intent(
        self,
        fallback: WorkflowStepDefinition,
        parent: AgentIntent,
        context: ConversationContext,
    ) -> AgentIntent:
        room = fallback.room
        if room == "context":
            room = parent.room or context.source_room or context.previous_room
        return AgentIntent(
            kind=IntentKind.ACTION,
            goal=parent.goal,
            action=fallback.action,
            target=fallback.target,
            room=room,
            domain_hint=fallback.domains[0] if len(fallback.domains) == 1 else None,
            selection=fallback.selection,
            confidence=parent.confidence,
            rationale=f"Fallback-Schritt fuer {parent.workflow}",
        )


def _plan_step(
    intent: AgentIntent,
    entities: list[EntityDescriptor],
    configured_data: dict[str, Any],
    workflow_name: str,
) -> PlanStep | None:
    service, dynamic_data, expected = action_service(intent, entities)
    if service is None:
        return None
    data = {**dynamic_data, **configured_data}
    if "brightness_pct" in data:
        expected = dict.fromkeys((entity.entity_id for entity in entities), "on")
    return PlanStep(
        domain=entities[0].domain,
        service=service,
        entity_ids=[entity.entity_id for entity in entities],
        data=data,
        expected_states=expected,
        reason=f"Dynamischer Schritt fuer {workflow_name}",
    )


def action_service(
    intent: AgentIntent,
    entities: list[EntityDescriptor],
) -> tuple[str | None, dict[str, Any], dict[str, str]]:
    """Map one abstract action to a validated domain service and payload."""
    if not entities:
        return None, {}, {}
    domain = entities[0].domain
    entity_ids = [entity.entity_id for entity in entities]
    expected: dict[str, str] = {}
    data: dict[str, Any] = {}
    if intent.action is ActionType.TURN_ON:
        expected = dict.fromkeys(entity_ids, "on")
        return "turn_on", data, expected
    if intent.action is ActionType.TURN_OFF:
        expected = dict.fromkeys(entity_ids, "off")
        return "turn_off", data, expected
    if intent.action is ActionType.TOGGLE:
        return "toggle", data, expected
    if intent.action is ActionType.ADJUST_BRIGHTNESS and domain == "light":
        if any(
            _finite_number(entity.attributes.get("brightness")) is None
            for entity in entities
        ):
            return None, {}, {}
        step = -20 if intent.direction == "decrease" else 20
        return "turn_on", {"brightness_step_pct": step}, dict.fromkeys(entity_ids, "on")
    if intent.action is ActionType.SET_BRIGHTNESS and domain == "light":
        value = _finite_number(intent.value)
        if value is None:
            return None, {}, {}
        value = max(0.0, min(100.0, value))
        if value == 0:
            return "turn_off", {}, dict.fromkeys(entity_ids, "off")
        return "turn_on", {"brightness_pct": value}, dict.fromkeys(entity_ids, "on")
    if intent.action is ActionType.ADJUST_COLOR_TEMPERATURE and domain == "light":
        kelvin = _adjusted_kelvin(entities[0], intent.direction)
        return "turn_on", {"color_temp_kelvin": kelvin}, dict.fromkeys(entity_ids, "on")
    if intent.action is ActionType.SET_COLOR_TEMPERATURE and domain == "light":
        value = _finite_number(intent.value)
        if value is None:
            return None, {}, {}
        return (
            "turn_on",
            {"color_temp_kelvin": int(value)},
            dict.fromkeys(entity_ids, "on"),
        )
    if intent.action is ActionType.SET_TEMPERATURE and domain == "climate":
        value = _finite_number(intent.value)
        if value is None:
            return None, {}, {}
        return "set_temperature", {"temperature": value}, {}
    service_map: dict[tuple[ActionType, str], str] = {
        (ActionType.OPEN, "cover"): "open_cover",
        (ActionType.CLOSE, "cover"): "close_cover",
        (ActionType.LOCK, "lock"): "lock",
        (ActionType.UNLOCK, "lock"): "unlock",
        (ActionType.PLAY, "media_player"): "media_play",
        (ActionType.PAUSE, "media_player"): "media_pause",
        (ActionType.STOP, "media_player"): "media_stop",
    }
    service = service_map.get((intent.action, domain))
    if service is None:
        return None, {}, {}
    expected_by_service = {
        "open_cover": "open",
        "close_cover": "closed",
        "lock": "locked",
        "unlock": "unlocked",
        "media_play": "playing",
        "media_pause": "paused",
        "media_stop": "idle",
    }
    expected_state = expected_by_service.get(service)
    if expected_state:
        expected = dict.fromkeys(entity_ids, expected_state)
    return service, data, expected


def _adjusted_kelvin(entity: EntityDescriptor, direction: str | None) -> int:
    current = entity.attributes.get("color_temp_kelvin")
    if not isinstance(current, int | float):
        current = 3200
    minimum = entity.attributes.get("min_color_temp_kelvin", 2000)
    maximum = entity.attributes.get("max_color_temp_kelvin", 6500)
    if not isinstance(minimum, int | float):
        minimum = 2000
    if not isinstance(maximum, int | float):
        maximum = 6500
    step = -400 if direction in {"warmer", "decrease"} else 400
    return int(max(float(minimum), min(float(maximum), float(current) + step)))


def _supports_data(entity: EntityDescriptor, data: dict[str, Any]) -> bool:
    if any(key in data for key in ("brightness_pct", "brightness_step_pct")):
        return "brightness" in entity.capabilities
    if "color_temp_kelvin" in data:
        return "color_temperature" in entity.capabilities
    return True


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None
