"""Typed models for durable conditional agent tasks."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from kira.agent.models import ActionPlan, AgentIntent, utc_now
from kira.homeassistant.permissions import PermissionDecision, RiskLevel


class TaskStatus(StrEnum):
    """Lifecycle states of a durable conditional task."""

    ACTIVE = "active"
    PENDING_CONFIRMATION = "pending_confirmation"
    DELEGATED = "delegated"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskActionKind(StrEnum):
    """Supported side-effect categories for a task."""

    HOME_ASSISTANT = "homeassistant"
    NOTIFY = "notify"


class TaskConditionKind(StrEnum):
    """Supported condition evaluation strategies."""

    STATE = "state"
    NUMERIC_BELOW = "numeric_below"


class TaskTrigger(BaseModel):
    """A state transition that may activate one task."""

    model_config = ConfigDict(extra="forbid")

    event_type: str = "state_changed"
    target: str
    entity_ids: list[str] = Field(default_factory=list)
    from_states: list[str] = Field(default_factory=list)
    to_states: list[str] = Field(default_factory=list)
    description: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class TaskCondition(BaseModel):
    """An additional live-state condition checked after the trigger."""

    model_config = ConfigDict(extra="forbid")

    kind: TaskConditionKind
    target: str
    entity_ids: list[str] = Field(default_factory=list)
    expected_states: list[str] = Field(default_factory=list)
    maximum: float | None = None
    description: str


class TaskAction(BaseModel):
    """A deferred Home Assistant action or notification."""

    model_config = ConfigDict(extra="forbid")

    kind: TaskActionKind
    intent: AgentIntent | None = None
    notification_text: str | None = None
    authorized_entity_ids: list[str] = Field(default_factory=list)


class TaskDraft(BaseModel):
    """Parsed task before safety classification and persistence."""

    model_config = ConfigDict(extra="forbid")

    request_text: str
    trigger: TaskTrigger
    conditions: list[TaskCondition] = Field(default_factory=list)
    actions: list[TaskAction]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class TaskParseResult(BaseModel):
    """Task parser result with a user-facing failure explanation."""

    model_config = ConfigDict(extra="forbid")

    draft: TaskDraft | None = None
    message: str = ""


class AgentTask(BaseModel):
    """One durable user-authorized conditional task."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str
    user: str | None = None
    source: str = "chat"
    source_room: str | None = None
    request_text: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    confirmation_expires_at: datetime | None = None
    status: TaskStatus
    safety_decision: PermissionDecision
    safety_classification: RiskLevel
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    trigger: TaskTrigger
    conditions: list[TaskCondition] = Field(default_factory=list)
    actions: list[TaskAction]
    preview_plan: ActionPlan | None = None
    delegated_automation_id: str | None = None
    confirmed_at: datetime | None = None
    last_result: str | None = None


class TaskDocument(BaseModel):
    """Versioned bounded task storage document."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    tasks: list[AgentTask] = Field(default_factory=list)
