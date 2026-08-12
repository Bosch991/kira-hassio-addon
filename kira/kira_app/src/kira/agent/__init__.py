"""Context-aware Home Assistant agent components."""

from kira.agent.context import ConversationContextStore
from kira.agent.entities import EntityCatalog, EntityResolver
from kira.agent.intents import (
    IntentResolver,
    LocalIntentResolver,
    OpenAIIntentInterpreter,
)
from kira.agent.models import (
    ActionPlan,
    ActionType,
    AgentIntent,
    AgentRequestContext,
    ConversationContext,
    IntentKind,
    MetricType,
    PlanStep,
    SelectionMode,
)
from kira.agent.proactive import (
    ProactiveDecision,
    ProactiveMode,
    ProactivePolicy,
    ProactiveSignal,
)

__all__ = [
    "ActionPlan",
    "ActionType",
    "AgentIntent",
    "AgentRequestContext",
    "ConversationContext",
    "ConversationContextStore",
    "EntityCatalog",
    "EntityResolver",
    "IntentKind",
    "IntentResolver",
    "LocalIntentResolver",
    "MetricType",
    "OpenAIIntentInterpreter",
    "PlanStep",
    "ProactiveDecision",
    "ProactiveMode",
    "ProactivePolicy",
    "ProactiveSignal",
    "SelectionMode",
]
