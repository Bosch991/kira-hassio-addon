"""Configurable goals, completion checks, preferences, and goal history."""

from __future__ import annotations

import logging
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

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
    utc_now,
)
from kira.agent.normalization import normalize_text, text_tokens
from kira.agent.persistence import AtomicDocumentStore
from kira.agent.situation import SituationContext


class CompletionMode(StrEnum):
    """How configured completion rules combine."""

    ALL = "all"
    ANY = "any"


class GoalStatus(StrEnum):
    """Lifecycle states stored for recent goals."""

    REQUESTED = "requested"
    PLANNED = "planned"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NumericExpectation(BaseModel):
    """Expected numeric attribute range, optionally centered on a preference."""

    model_config = ConfigDict(extra="forbid")

    minimum: float | None = None
    maximum: float | None = None
    preference_key: str | None = None
    tolerance: float = Field(default=2.0, ge=0.0)


class GoalCompletionRule(BaseModel):
    """Selector and desired state for one part of a goal."""

    model_config = ConfigDict(extra="forbid")

    target: str
    domains: list[str] = Field(default_factory=list)
    room: str | None = "goal"
    states: list[str] = Field(default_factory=list)
    state_preference_key: str | None = None
    attributes: dict[str, NumericExpectation] = Field(default_factory=dict)
    selection: SelectionMode = SelectionMode.ALL
    match: CompletionMode = CompletionMode.ALL
    optional: bool = False


class PreferencePlanMapping(BaseModel):
    """Whitelisted mapping from one preference into matching plan steps."""

    model_config = ConfigDict(extra="forbid")

    entity_tags: list[str] = Field(default_factory=list)
    data_key: str | None = None
    service_by_value: dict[str, str] = Field(default_factory=dict)


class GoalDefinition(BaseModel):
    """One configurable household goal."""

    model_config = ConfigDict(extra="forbid")

    name: str
    aliases: list[str] = Field(default_factory=list)
    workflow: str | None = None
    activity: str | None = None
    default_room: str | None = None
    completion_mode: CompletionMode = CompletionMode.ALL
    completion: list[GoalCompletionRule] = Field(default_factory=list)
    preference_mappings: dict[str, PreferencePlanMapping] = Field(default_factory=dict)
    completed_message: str = "Das Ziel ist bereits erreicht."


class GoalDocument(BaseModel):
    """Versioned goal configuration."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    goals: dict[str, GoalDefinition] = Field(default_factory=dict)


class Goal(BaseModel):
    """One abstract user goal before Home Assistant planning."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    name: str
    room: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    workflow: str | None = None
    activity: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str
    requested_at: datetime = Field(default_factory=utc_now)


class GoalResolution(BaseModel):
    """Goal resolution outcome with a non-fatal reason."""

    model_config = ConfigDict(extra="forbid")

    goal: Goal | None = None
    reason: str = ""


class GoalCompletionResult(BaseModel):
    """Explain whether and why a goal is currently complete."""

    model_config = ConfigDict(extra="forbid")

    completed: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    unmet: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)


class GoalRecord(BaseModel):
    """Persisted lifecycle record for one recent goal."""

    model_config = ConfigDict(extra="forbid")

    goal: Goal
    conversation_id: str
    user: str | None = None
    status: GoalStatus = GoalStatus.REQUESTED
    plan_id: str | None = None
    result: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class GoalHistoryDocument(BaseModel):
    """Versioned bounded goal history."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    records: list[GoalRecord] = Field(default_factory=list)


class GoalHistoryStore:
    """Persist recent goal outcomes separately from conversation context."""

    def __init__(self, path: Path, *, limit: int = 100) -> None:
        """Initialize bounded typed storage."""
        self.limit = max(10, limit)
        self._store = AtomicDocumentStore(
            path,
            document_type=GoalHistoryDocument,
            empty_factory=GoalHistoryDocument,
        )

    def initialize(self) -> None:
        """Create an empty history when missing."""
        self._store.initialize()

    def record(
        self,
        goal: Goal,
        *,
        conversation_id: str,
        user: str | None,
        status: GoalStatus = GoalStatus.REQUESTED,
        plan_id: str | None = None,
        result: str | None = None,
    ) -> GoalRecord:
        """Create or update one goal record."""
        saved: GoalRecord | None = None

        def mutate(document: GoalHistoryDocument) -> None:
            nonlocal saved
            existing = next(
                (item for item in document.records if item.goal.id == goal.id),
                None,
            )
            if existing is None:
                existing = GoalRecord(
                    goal=goal,
                    conversation_id=conversation_id,
                    user=user,
                )
                document.records.append(existing)
            existing.status = status
            existing.plan_id = plan_id or existing.plan_id
            existing.result = result
            existing.updated_at = utc_now()
            document.records = sorted(
                document.records,
                key=lambda item: item.updated_at,
                reverse=True,
            )[: self.limit]
            saved = existing.model_copy(deep=True)

        self._store.update(mutate)
        assert saved is not None
        return saved

    def recent(
        self,
        *,
        user: str | None = None,
        limit: int = 10,
    ) -> list[GoalRecord]:
        """Return recent records for an optional user."""
        records = self._store.read().records
        if user is not None:
            records = [item for item in records if item.user == user]
        return sorted(records, key=lambda item: item.updated_at, reverse=True)[:limit]

    def get(self, goal_id: str) -> GoalRecord | None:
        """Return one goal record by its stable ID."""
        return next(
            (item for item in self._store.read().records if item.goal.id == goal_id),
            None,
        )


class GoalResolver:
    """Resolve configurable goals without a hard-coded goal switch."""

    def __init__(self, path: Path) -> None:
        """Initialize and load goal definitions."""
        self.path = path
        self.document = GoalDocument()
        self.logger = logging.getLogger(__name__)
        self.reload()

    def reload(self) -> None:
        """Reload goals while preserving the last valid document on error."""
        if not self.path.exists():
            self.document = GoalDocument()
            return
        try:
            payload = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            document = GoalDocument.model_validate(payload)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            self.logger.warning("Agent goals could not be reloaded: %s", exc)
            return
        self.document = document

    def resolve(
        self,
        message: str,
        intent: AgentIntent,
        context: ConversationContext,
        situation: SituationContext,
    ) -> GoalResolution:
        """Resolve one request to an abstract configured goal."""
        match = self._match(message, intent)
        if match is None:
            return GoalResolution(reason="no_configured_goal")
        goal_type, definition, confidence, source = match
        room = (
            intent.room
            or context.source_room
            or context.previous_room
            or (
                situation.active_room.value
                if situation.active_room is not None
                and situation.active_room.confidence >= 0.65
                else None
            )
            or definition.default_room
        )
        if room and situation.active_room is not None:
            if normalize_text(room) == normalize_text(situation.active_room.value):
                confidence = min(
                    0.99,
                    max(confidence, situation.active_room.confidence),
                )
        return GoalResolution(
            goal=Goal(
                type=goal_type,
                name=definition.name,
                room=room,
                parameters={"request": message},
                workflow=definition.workflow,
                activity=definition.activity,
                confidence=confidence,
                source=source,
            ),
            reason="configured_goal",
        )

    def definition(self, goal: Goal) -> GoalDefinition | None:
        """Return the current definition for one resolved goal."""
        return self.document.goals.get(goal.type)

    def _match(
        self,
        message: str,
        intent: AgentIntent,
    ) -> tuple[str, GoalDefinition, float, str] | None:
        if intent.workflow:
            workflow_match = next(
                (
                    (key, definition)
                    for key, definition in self.document.goals.items()
                    if definition.workflow == intent.workflow
                ),
                None,
            )
            if workflow_match is not None:
                return (
                    *workflow_match,
                    max(0.94, intent.confidence),
                    "intent_workflow",
                )
        text = normalize_text(f"{message} {intent.goal}")
        candidates = [
            (len(normalize_text(alias)), key, definition)
            for key, definition in self.document.goals.items()
            for alias in definition.aliases
            if normalize_text(alias) and normalize_text(alias) in text
        ]
        if not candidates:
            return None
        _length, key, definition = max(candidates, key=lambda item: item[0])
        return key, definition, max(0.88, intent.confidence), "configured_alias"


class GoalCompletionEvaluator:
    """Evaluate configured completion rules against current trusted entities."""

    def __init__(self, resolver: EntityResolver, goals: GoalResolver) -> None:
        """Initialize shared entity and goal definitions."""
        self.resolver = resolver
        self.goals = goals

    def evaluate(
        self,
        goal: Goal,
        context: ConversationContext,
        catalog: EntityCatalog,
        *,
        preferences: dict[str, Any] | None = None,
    ) -> GoalCompletionResult:
        """Return completion without causing any service call."""
        definition = self.goals.definition(goal)
        if definition is None or not definition.completion:
            return GoalCompletionResult(
                completed=False,
                unmet=["no_completion_rules"],
            )
        preferences = preferences or {}
        rule_results: list[bool] = []
        evidence: list[str] = []
        unmet: list[str] = []
        entity_ids: list[str] = []
        confidences: list[float] = []
        for rule in definition.completion:
            matches = self._matches(rule, goal, context, catalog)
            if not matches:
                if rule.optional:
                    evidence.append(f"optional_missing:{rule.target}")
                    continue
                rule_results.append(False)
                unmet.append(f"missing:{rule.target}")
                continue
            checks = [
                self._entity_matches(entity, rule, preferences) for entity in matches
            ]
            passed = all(checks) if rule.match is CompletionMode.ALL else any(checks)
            rule_results.append(passed)
            entity_ids.extend(item.entity_id for item in matches)
            confidences.extend(max(item.area_confidence, 0.85) for item in matches)
            evidence.extend(
                f"{item.entity_id}={item.state}:{'ok' if check else 'unmet'}"
                for item, check in zip(matches, checks, strict=True)
            )
            if not passed:
                unmet.append(rule.target)
        if not rule_results:
            return GoalCompletionResult(
                completed=False,
                evidence=evidence,
                unmet=["no_required_completion_signal"],
                entity_ids=list(dict.fromkeys(entity_ids)),
            )
        completed = (
            all(rule_results)
            if definition.completion_mode is CompletionMode.ALL
            else any(rule_results)
        )
        confidence = min(
            goal.confidence,
            sum(confidences) / len(confidences) if confidences else 0.65,
        )
        return GoalCompletionResult(
            completed=completed,
            confidence=confidence,
            evidence=evidence,
            unmet=unmet,
            entity_ids=list(dict.fromkeys(entity_ids)),
        )

    def _matches(
        self,
        rule: GoalCompletionRule,
        goal: Goal,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> list[EntityDescriptor]:
        room = goal.room if rule.room == "goal" else rule.room
        intent = AgentIntent(
            kind=IntentKind.QUERY,
            goal=goal.type,
            action=ActionType.QUERY_STATE,
            target=rule.target,
            room=room,
            domain_hint=rule.domains[0] if len(rule.domains) == 1 else None,
            selection=rule.selection,
            confidence=goal.confidence,
        )
        resolution = self.resolver.resolve(intent, context, catalog)
        matches = [
            item
            for item in resolution.matches
            if not rule.domains or item.domain in rule.domains
        ]
        specific_tokens = text_tokens(rule.target) - {
            "alle",
            "das",
            "die",
            "geraet",
            "geraete",
            "lampe",
            "lampen",
            "licht",
            "lichter",
        }
        if not specific_tokens:
            return matches
        specific = [
            item
            for item in matches
            if any(token in item.search_text for token in specific_tokens)
        ]
        return specific or matches

    def _entity_matches(
        self,
        entity: EntityDescriptor,
        rule: GoalCompletionRule,
        preferences: dict[str, Any],
    ) -> bool:
        desired_states = list(rule.states)
        if rule.state_preference_key:
            preferred = preferences.get(rule.state_preference_key)
            if isinstance(preferred, str) and preferred.strip():
                desired_states = [preferred]
        if desired_states and normalize_text(entity.state) not in {
            normalize_text(item) for item in desired_states
        }:
            return False
        for name, expectation in rule.attributes.items():
            value = _attribute_number(entity, name)
            if value is None:
                return False
            minimum = expectation.minimum
            maximum = expectation.maximum
            if expectation.preference_key:
                preferred = _number(preferences.get(expectation.preference_key))
                if preferred is not None:
                    minimum = preferred - expectation.tolerance
                    maximum = preferred + expectation.tolerance
            if minimum is not None and value < minimum:
                return False
            if maximum is not None and value > maximum:
                return False
        return True


class GoalPlanAdapter:
    """Apply only explicitly whitelisted preferences to an existing plan."""

    def apply(
        self,
        plan: ActionPlan,
        *,
        goal: Goal,
        definition: GoalDefinition,
        preferences: dict[str, Any],
        catalog: EntityCatalog,
    ) -> ActionPlan:
        """Return a preference-aware copy with reasons preserved in each step."""
        steps = [step.model_copy(deep=True) for step in plan.steps]
        changed: list[str] = []
        for preference_key, mapping in definition.preference_mappings.items():
            if preference_key not in preferences:
                continue
            value = preferences[preference_key]
            for index, step in enumerate(steps):
                if not self._matches_step(step, mapping, catalog):
                    continue
                data = dict(step.data)
                service = step.service
                expected = dict(step.expected_states)
                if mapping.data_key and _number(value) is not None:
                    data[mapping.data_key] = _number(value)
                mapped_service = mapping.service_by_value.get(
                    normalize_text(str(value))
                )
                if mapped_service:
                    service = mapped_service
                    state = "on" if mapped_service == "turn_on" else "off"
                    expected = dict.fromkeys(step.entity_ids, state)
                steps[index] = step.model_copy(
                    update={
                        "service": service,
                        "data": data,
                        "expected_states": expected,
                        "reason": (
                            f"{step.reason}; explizite Praeferenz "
                            f"{preference_key}={value}"
                        ),
                    }
                )
                changed.append(preference_key)
        if not changed:
            return plan
        return plan.model_copy(
            update={
                "goal": goal.type,
                "steps": steps,
                "explanation": (
                    f"{plan.explanation} Explizite Praeferenzen angewendet: "
                    f"{', '.join(dict.fromkeys(changed))}."
                ),
            }
        )

    def _matches_step(
        self,
        step: PlanStep,
        mapping: PreferencePlanMapping,
        catalog: EntityCatalog,
    ) -> bool:
        required = {normalize_text(item) for item in mapping.entity_tags}
        if not required:
            return True
        return any(
            required
            & {
                *(normalize_text(item) for item in entity.tags),
                *(normalize_text(item) for item in entity.used_for),
            }
            for entity_id in step.entity_ids
            if (entity := catalog.by_id.get(entity_id)) is not None
        )


def _attribute_number(entity: EntityDescriptor, name: str) -> float | None:
    if name == "brightness_pct":
        direct = _number(entity.attributes.get("brightness_pct"))
        if direct is not None:
            return direct
        brightness = _number(entity.attributes.get("brightness"))
        return brightness / 255 * 100 if brightness is not None else None
    return _number(entity.attributes.get(name))


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
