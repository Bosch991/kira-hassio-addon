"""Atomic persistence and event matching for conditional tasks."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from kira.agent.entities import EntityCatalog
from kira.agent.models import ActionPlan, ConversationContext, utc_now
from kira.agent.normalization import normalize_text, text_tokens
from kira.agent.persistence import AtomicDocumentStore
from kira.agent.task_models import (
    AgentTask,
    TaskCondition,
    TaskConditionKind,
    TaskDocument,
    TaskDraft,
    TaskStatus,
    TaskTrigger,
)
from kira.homeassistant.events import HomeAssistantLiveEvent
from kira.homeassistant.permissions import PermissionDecision, RiskLevel


class TaskManager:
    """Persist tasks and match active triggers without executing actions."""

    def __init__(self, path: Path, *, limit: int = 250) -> None:
        """Initialize bounded atomic task storage."""
        self.limit = max(25, limit)
        self._store = AtomicDocumentStore(
            path,
            document_type=TaskDocument,
            empty_factory=TaskDocument,
        )

    @property
    def path(self) -> Path:
        """Return the task JSON path."""
        return self._store.path

    def initialize(self) -> None:
        """Create storage and recover interrupted or expired lifecycle states."""
        self._store.initialize()
        now = utc_now()

        def recover(document: TaskDocument) -> None:
            for task in document.tasks:
                if task.status is TaskStatus.RUNNING:
                    task.status = TaskStatus.FAILED
                    task.last_result = "interrupted_during_execution"
                    task.updated_at = now
                elif (
                    task.status is TaskStatus.PENDING_CONFIRMATION
                    and task.confirmation_expires_at is not None
                    and now > task.confirmation_expires_at
                ):
                    task.status = TaskStatus.EXPIRED
                    task.last_result = "confirmation_expired"
                    task.updated_at = now

        self._store.update(recover)

    def create(
        self,
        draft: TaskDraft,
        context: ConversationContext,
        *,
        decision: PermissionDecision,
        risk: RiskLevel,
        preview_plan: ActionPlan | None = None,
        delegated_automation_id: str | None = None,
        confirmation_expires_at: datetime | None = None,
    ) -> AgentTask:
        """Classify and persist one parsed task."""
        if delegated_automation_id:
            status = TaskStatus.DELEGATED
        elif decision is PermissionDecision.BLOCK:
            status = TaskStatus.BLOCKED
        elif decision is PermissionDecision.REQUIRE_CONFIRM:
            status = TaskStatus.PENDING_CONFIRMATION
        else:
            status = TaskStatus.ACTIVE
        task = AgentTask(
            conversation_id=context.conversation_id,
            user=context.user,
            source=context.source,
            source_room=context.source_room,
            request_text=draft.request_text,
            status=status,
            safety_decision=decision,
            safety_classification=risk,
            confidence=draft.confidence,
            evidence=list(draft.evidence),
            trigger=draft.trigger,
            conditions=draft.conditions,
            actions=draft.actions,
            preview_plan=preview_plan,
            delegated_automation_id=delegated_automation_id,
            confirmation_expires_at=confirmation_expires_at,
        )

        def mutate(document: TaskDocument) -> None:
            document.tasks.append(task)
            document.tasks = sorted(
                document.tasks,
                key=lambda item: item.updated_at,
                reverse=True,
            )[: self.limit]

        self._store.update(mutate)
        return task.model_copy(deep=True)

    def get(self, task_id: str) -> AgentTask | None:
        """Return one task by ID."""
        return next(
            (item for item in self._store.read().tasks if item.id == task_id),
            None,
        )

    def list(
        self,
        *,
        statuses: set[TaskStatus] | None = None,
        user: str | None = None,
    ) -> list[AgentTask]:
        """Return tasks newest first with optional filters."""
        tasks = self._store.read().tasks
        if statuses is not None:
            tasks = [item for item in tasks if item.status in statuses]
        if user is not None:
            tasks = [item for item in tasks if item.user == user]
        return sorted(tasks, key=lambda item: item.updated_at, reverse=True)

    def activate(self, task_id: str) -> AgentTask | None:
        """Activate a task after explicit confirmation."""
        task = self.get(task_id)
        if task is None or task.status is not TaskStatus.PENDING_CONFIRMATION:
            return None
        if (
            task.confirmation_expires_at is not None
            and utc_now() > task.confirmation_expires_at
        ):
            self._transition(
                task_id,
                status=TaskStatus.EXPIRED,
                result="confirmation_expired",
            )
            return None
        return self._transition(
            task_id,
            status=TaskStatus.ACTIVE,
            confirmed_at=utc_now(),
            result="explicitly_confirmed",
        )

    def cancel(self, task_id: str) -> AgentTask | None:
        """Cancel one pending or active task."""
        return self._transition(
            task_id,
            status=TaskStatus.CANCELLED,
            result="cancelled_by_user",
        )

    def mark_running(self, task_id: str) -> AgentTask | None:
        """Claim a matched task before execution."""
        return self._transition(task_id, status=TaskStatus.RUNNING, result="triggered")

    def complete(self, task_id: str, result: str) -> AgentTask | None:
        """Mark a task completed."""
        return self._transition(task_id, status=TaskStatus.COMPLETED, result=result)

    def fail(self, task_id: str, result: str) -> AgentTask | None:
        """Mark a task failed."""
        return self._transition(task_id, status=TaskStatus.FAILED, result=result)

    def defer_confirmation(self, task_id: str, result: str) -> AgentTask | None:
        """Require a fresh confirmation after a material runtime plan change."""
        return self._transition(
            task_id,
            status=TaskStatus.PENDING_CONFIRMATION,
            result=result,
        )

    def match_event(
        self,
        event: HomeAssistantLiveEvent,
        catalog: EntityCatalog,
        *,
        now: datetime | None = None,
    ) -> list[AgentTask]:
        """Return active tasks whose trigger and conditions match one event."""
        current = now or utc_now()
        matches: list[AgentTask] = []
        for task in self.list(statuses={TaskStatus.ACTIVE}):
            if task.expires_at is not None and current > task.expires_at:
                self._transition(
                    task.id,
                    status=TaskStatus.EXPIRED,
                    result="expiry_reached",
                )
                continue
            if not self._trigger_matches(task.trigger, event):
                continue
            if not all(
                self._condition_matches(item, catalog) for item in task.conditions
            ):
                continue
            matches.append(task)
        return matches

    def find_existing_automation(
        self,
        draft: TaskDraft,
        catalog: EntityCatalog,
    ) -> str | None:
        """Return a strongly matching HA automation instead of duplicating it."""
        trigger_tokens = _meaningful_tokens(draft.trigger.description)
        action_tokens = _meaningful_tokens(draft.request_text.split(",", 1)[-1])
        candidates: list[tuple[int, str]] = []
        for entity in catalog.entities:
            if (
                entity.domain != "automation"
                or not entity.available
                or entity.state == "off"
            ):
                continue
            entity_tokens = text_tokens(entity.search_text)
            trigger_overlap = trigger_tokens & entity_tokens
            action_overlap = action_tokens & entity_tokens
            score = len(trigger_overlap) + len(action_overlap)
            if trigger_overlap and action_overlap and score >= 3:
                candidates.append((score, entity.entity_id))
        return max(candidates)[1] if candidates else None

    def _transition(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        result: str,
        confirmed_at: datetime | None = None,
    ) -> AgentTask | None:
        updated: AgentTask | None = None

        def mutate(document: TaskDocument) -> None:
            nonlocal updated
            task = next((item for item in document.tasks if item.id == task_id), None)
            if task is None:
                return
            task.status = status
            task.last_result = result
            task.updated_at = utc_now()
            if confirmed_at is not None:
                task.confirmed_at = confirmed_at
            updated = task.model_copy(deep=True)

        self._store.update(mutate)
        return updated

    def _trigger_matches(
        self,
        trigger: TaskTrigger,
        event: HomeAssistantLiveEvent,
    ) -> bool:
        if event.event_type != trigger.event_type:
            return False
        if trigger.entity_ids and event.entity_id not in trigger.entity_ids:
            return False
        old_state = normalize_text(event.old_state or "")
        new_state = normalize_text(event.new_state or "")
        if trigger.from_states and old_state not in {
            normalize_text(item) for item in trigger.from_states
        }:
            return False
        return not trigger.to_states or new_state in {
            normalize_text(item) for item in trigger.to_states
        }

    def _condition_matches(
        self,
        condition: TaskCondition,
        catalog: EntityCatalog,
    ) -> bool:
        entities = [
            catalog.by_id[entity_id]
            for entity_id in condition.entity_ids
            if entity_id in catalog.by_id
        ]
        if not entities:
            return False
        if condition.kind is TaskConditionKind.STATE:
            expected = {normalize_text(item) for item in condition.expected_states}
            return any(normalize_text(item.state) in expected for item in entities)
        if condition.kind is TaskConditionKind.NUMERIC_BELOW:
            maximum = condition.maximum
            if maximum is None:
                return False
            return any(
                (value := _number(item.state)) is not None and value < maximum
                for item in entities
            )
        return False


def _meaningful_tokens(value: str) -> set[str]:
    """Return content tokens used for conservative automation matching."""
    return text_tokens(value) - {
        "als",
        "dann",
        "das",
        "den",
        "der",
        "die",
        "ein",
        "eine",
        "ich",
        "ist",
        "mach",
        "mir",
        "schalte",
        "wenn",
    }


def _number(value: Any) -> float | None:
    """Parse finite numeric states used by task conditions."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None
