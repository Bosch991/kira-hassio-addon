"""Context-aware Home Assistant agent components."""

from kira.agent.context import ConversationContextStore
from kira.agent.entities import EntityCatalog, EntityResolver
from kira.agent.fusion import ContextFusionEngine, FusedContext
from kira.agent.goal_runtime import GoalRuntime
from kira.agent.goals import (
    Goal,
    GoalCompletionEvaluator,
    GoalResolver,
    GoalStatus,
)
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
    ProactiveEngine,
    ProactiveMode,
    ProactivePolicy,
    ProactiveSignal,
)
from kira.agent.situation import SituationAnalyzer, SituationContext
from kira.agent.tasks import AgentTask, TaskManager, TaskParser, TaskStatus

__all__ = [
    "ActionPlan",
    "ActionType",
    "AgentIntent",
    "AgentRequestContext",
    "AgentTask",
    "ConversationContext",
    "ConversationContextStore",
    "ContextFusionEngine",
    "EntityCatalog",
    "EntityResolver",
    "FusedContext",
    "Goal",
    "GoalCompletionEvaluator",
    "GoalResolver",
    "GoalRuntime",
    "GoalStatus",
    "IntentKind",
    "IntentResolver",
    "LocalIntentResolver",
    "MetricType",
    "OpenAIIntentInterpreter",
    "PlanStep",
    "ProactiveDecision",
    "ProactiveEngine",
    "ProactiveMode",
    "ProactivePolicy",
    "ProactiveSignal",
    "SelectionMode",
    "SituationAnalyzer",
    "SituationContext",
    "TaskManager",
    "TaskParser",
    "TaskStatus",
]
