"""Typed models shared by Kira's Home Assistant agent pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


class IntentKind(StrEnum):
    """High-level meaning of one user message."""

    CONVERSATION = "conversation"
    QUERY = "query"
    ACTION = "action"
    WORKFLOW = "workflow"
    CONFIRM = "confirm"
    CANCEL = "cancel"


class ActionType(StrEnum):
    """Abstract actions accepted from semantic interpretation."""

    NONE = "none"
    QUERY_STATE = "query_state"
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    TOGGLE = "toggle"
    ADJUST_BRIGHTNESS = "adjust_brightness"
    SET_BRIGHTNESS = "set_brightness"
    ADJUST_COLOR_TEMPERATURE = "adjust_color_temperature"
    SET_COLOR_TEMPERATURE = "set_color_temperature"
    SET_TEMPERATURE = "set_temperature"
    OPEN = "open"
    CLOSE = "close"
    LOCK = "lock"
    UNLOCK = "unlock"
    PLAY = "play"
    PAUSE = "pause"
    STOP = "stop"


class MetricType(StrEnum):
    """Read-only values Kira can retrieve from Home Assistant."""

    NONE = "none"
    STATE = "state"
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    BATTERY = "battery"
    POWER = "power"
    ENERGY = "energy"
    VOLTAGE = "voltage"
    CURRENT = "current"
    PRESSURE = "pressure"
    ILLUMINANCE = "illuminance"
    AIR_QUALITY = "air_quality"


class SelectionMode(StrEnum):
    """How matching entities should be selected."""

    AUTO = "auto"
    SINGLE = "single"
    ALL = "all"


class AgentIntent(BaseModel):
    """Structured and provider-independent interpretation of a request."""

    model_config = ConfigDict(extra="forbid")

    kind: IntentKind = IntentKind.CONVERSATION
    goal: str = ""
    action: ActionType = ActionType.NONE
    target: str | None = None
    room: str | None = None
    domain_hint: str | None = None
    metric: MetricType = MetricType.NONE
    state_filter: list[str] = Field(default_factory=list)
    selection: SelectionMode = SelectionMode.AUTO
    value: float | None = None
    direction: str | None = None
    color: str | None = None
    workflow: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""

    @field_validator(
        "room",
        "domain_hint",
        "direction",
        "color",
        "workflow",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        """Turn common model sentinel strings into real null values."""
        if isinstance(value, str) and value.strip().lower() in {
            "",
            "kein",
            "keine",
            "none",
            "null",
            "unknown",
        }:
            return None
        return value


class AgentRequestContext(BaseModel):
    """Origin metadata accompanying a user request."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = None
    user: str | None = None
    source: str = "chat"
    source_device: str | None = None
    source_room: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)


class PlanStep(BaseModel):
    """One validated candidate step in a Home Assistant plan."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    domain: str
    service: str
    entity_ids: list[str]
    data: dict[str, Any] = Field(default_factory=dict)
    expected_states: dict[str, str] = Field(default_factory=dict)
    reason: str
    optional: bool = False


class ActionPlan(BaseModel):
    """Ordered and serializable Home Assistant action plan."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    goal: str
    intent: str
    steps: list[PlanStep]
    explanation: str
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None


class ConversationContext(BaseModel):
    """Durable context for one conversation or Assist pipeline."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    user: str | None = None
    source: str = "chat"
    source_device: str | None = None
    source_room: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    previous_intent: AgentIntent | None = None
    previous_entities: list[str] = Field(default_factory=list)
    previous_room: str | None = None
    previous_action: ActionType = ActionType.NONE
    pending_plan: ActionPlan | None = None
    pending_user: str | None = None
    pending_source: str | None = None


class ConversationContextDocument(BaseModel):
    """Versioned JSON document containing conversation contexts."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    contexts: dict[str, ConversationContext] = Field(default_factory=dict)
