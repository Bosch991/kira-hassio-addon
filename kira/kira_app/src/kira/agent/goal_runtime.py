"""Goal lifecycle facade used by the central agent coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from kira.agent.entities import EntityCatalog
from kira.agent.goals import (
    Goal,
    GoalCompletionEvaluator,
    GoalCompletionResult,
    GoalHistoryStore,
    GoalPlanAdapter,
    GoalResolver,
    GoalStatus,
)
from kira.agent.models import (
    ActionPlan,
    AgentIntent,
    ConversationContext,
    IntentKind,
    utc_now,
)
from kira.agent.preferences import PreferenceStore
from kira.agent.situation import SituationContext


@dataclass(frozen=True, slots=True)
class GoalContext:
    """Resolved goal together with its explicit preference scope."""

    goal: Goal
    preferences: dict[str, Any]


class GoalRuntime:
    """Coordinate goal-specific services behind one narrow interface."""

    def __init__(
        self,
        *,
        resolver: GoalResolver,
        completion: GoalCompletionEvaluator | None = None,
        plan_adapter: GoalPlanAdapter | None = None,
        history: GoalHistoryStore | None = None,
        preferences: PreferenceStore | None = None,
    ) -> None:
        """Initialize optional goal lifecycle capabilities."""
        self.resolver = resolver
        self.completion_evaluator = completion
        self.plan_adapter = plan_adapter
        self.history = history
        self.preference_store = preferences

    def resolve(
        self,
        message: str,
        intent: AgentIntent,
        context: ConversationContext,
        situation: SituationContext,
    ) -> GoalContext | None:
        """Resolve one configured goal and load only explicit preferences."""
        goal = self.resolver.resolve(message, intent, context, situation).goal
        if goal is None:
            return None
        return GoalContext(goal=goal, preferences=self.preferences(goal, context))

    def preferences(
        self,
        goal: Goal,
        context: ConversationContext,
    ) -> dict[str, Any]:
        """Return explicit values for this user, activity, and room."""
        if self.preference_store is None:
            return {}
        return self.preference_store.values_for(
            user=context.user,
            activity=goal.activity or goal.type,
            room=goal.room,
        )

    def completion(
        self,
        goal: Goal,
        context: ConversationContext,
        catalog: EntityCatalog,
        preferences: dict[str, Any],
    ) -> GoalCompletionResult | None:
        """Evaluate configured completion without any side effect."""
        if self.completion_evaluator is None:
            return None
        return self.completion_evaluator.evaluate(
            goal,
            context,
            catalog,
            preferences=preferences,
        )

    def effective_intent(
        self,
        intent: AgentIntent,
        goal: Goal | None,
    ) -> AgentIntent:
        """Project an abstract goal onto the existing planner contract."""
        if goal is None:
            return intent
        return intent.model_copy(
            update={
                "kind": IntentKind.WORKFLOW if goal.workflow else intent.kind,
                "goal": goal.type,
                "room": goal.room or intent.room,
                "workflow": goal.workflow or intent.workflow,
                "confidence": min(intent.confidence, goal.confidence),
                "rationale": (
                    intent.rationale or f"Konfiguriertes Benutzerziel: {goal.name}"
                ),
            }
        )

    def prepare_plan(
        self,
        plan: ActionPlan,
        *,
        goal: Goal,
        intent: AgentIntent,
        preferences: dict[str, Any],
        catalog: EntityCatalog,
    ) -> ActionPlan:
        """Attach goal identity/confidence and whitelisted preferences."""
        prepared = plan.model_copy(
            update={
                "goal": goal.type,
                "goal_id": goal.id,
                "confidence": min(goal.confidence, intent.confidence),
            }
        )
        definition = self.resolver.definition(goal)
        if definition is None or self.plan_adapter is None:
            return prepared
        return self.plan_adapter.apply(
            prepared,
            goal=goal,
            definition=definition,
            preferences=preferences,
            catalog=catalog,
        )

    def completed_message(self, goal: Goal) -> str:
        """Return the configured no-op completion response."""
        definition = self.resolver.definition(goal)
        return (
            definition.completed_message
            if definition is not None
            else "Das Ziel ist bereits erreicht."
        )

    def record(
        self,
        goal: Goal,
        context: ConversationContext,
        *,
        status: GoalStatus,
        plan_id: str | None = None,
        result: str | None = None,
    ) -> None:
        """Persist one goal transition outside conversation context."""
        if self.history is None:
            return
        self.history.record(
            goal,
            conversation_id=context.conversation_id,
            user=context.user,
            status=status,
            plan_id=plan_id,
            result=result,
        )

    def record_plan(
        self,
        plan: ActionPlan,
        context: ConversationContext,
        *,
        status: GoalStatus,
        result: str,
    ) -> None:
        """Record a transition for a goal referenced by a persisted plan."""
        goal = self.from_plan(plan)
        if goal is not None:
            self.record(
                goal,
                context,
                status=status,
                plan_id=plan.id,
                result=result,
            )

    def from_plan(self, plan: ActionPlan) -> Goal | None:
        """Recover a goal after a confirmation round-trip."""
        if plan.goal_id is None or self.history is None:
            return None
        record = self.history.get(plan.goal_id)
        return record.goal if record is not None else None

    def recent_context(
        self,
        context: ConversationContext,
        *,
        limit: int = 5,
        max_age: timedelta = timedelta(hours=12),
    ) -> list[dict[str, Any]]:
        """Return bounded successful recent goals for context, not memory."""
        if self.history is None:
            return []
        now = utc_now()
        records = self.history.recent(user=context.user, limit=max(limit * 4, 10))
        if context.user is None:
            records = [
                item
                for item in records
                if item.conversation_id == context.conversation_id
            ]
        return [
            {
                "type": item.goal.type,
                "name": item.goal.name,
                "room": item.goal.room,
                "status": item.status,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in records
            if item.status in {GoalStatus.PLANNED, GoalStatus.COMPLETED}
            and item.result != "awaiting_confirmation"
            and now - item.updated_at <= max_age
        ][:limit]
