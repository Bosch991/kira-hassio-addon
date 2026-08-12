"""Coordinate the context-aware Home Assistant agent pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any

from pydantic import BaseModel

from kira.agent.context import ConversationContextStore
from kira.agent.entities import EntityCatalog, EntityResolver
from kira.agent.execution import ActionExecutor
from kira.agent.fusion import ContextFusionEngine, FusedContext
from kira.agent.goal_runtime import GoalRuntime
from kira.agent.goals import (
    Goal,
    GoalCompletionEvaluator,
    GoalHistoryStore,
    GoalPlanAdapter,
    GoalResolver,
    GoalStatus,
)
from kira.agent.intents import IntentResolver
from kira.agent.models import (
    ActionPlan,
    AgentIntent,
    AgentRequestContext,
    ConversationContext,
    IntentKind,
)
from kira.agent.planning import HomeAssistantPlanner
from kira.agent.preferences import PreferenceStore
from kira.agent.proactive import ProactiveDecision, ProactiveEngine, ProactivePolicy
from kira.agent.responses import (
    ActionResponseBuilder,
    QueryResponseBuilder,
    plan_entity_names,
)
from kira.agent.safety import PlanSafetyManager
from kira.agent.situation import SituationAnalyzer, SituationContext
from kira.agent.task_runtime import TaskService
from kira.homeassistant.permissions import PermissionDecision
from kira.homeassistant.world_model import (
    HomeAssistantWorldModel,
    HomeAssistantWorldSnapshot,
)


@dataclass(frozen=True, slots=True)
class AgentResponse:
    """Result returned to a chat surface by the HA agent."""

    handled: bool
    response: str = ""
    intent: AgentIntent | None = None
    entity_ids: tuple[str, ...] = ()
    plan_id: str | None = None
    needs_confirmation: bool = False
    goal_id: str | None = None
    goal_completed: bool = False
    task_id: str | None = None


class HomeAssistantAgent:
    """Run context, intent, planning, safety, execution, and verification."""

    def __init__(
        self,
        *,
        world: HomeAssistantWorldModel,
        contexts: ConversationContextStore,
        intents: IntentResolver,
        entity_resolver: EntityResolver,
        planner: HomeAssistantPlanner,
        safety: PlanSafetyManager,
        executor: ActionExecutor,
        confirmation_seconds: int = 120,
        situation_analyzer: SituationAnalyzer | None = None,
        preference_store: PreferenceStore | None = None,
        context_fusion: ContextFusionEngine | None = None,
        goal_resolver: GoalResolver | None = None,
        goal_completion: GoalCompletionEvaluator | None = None,
        goal_plan_adapter: GoalPlanAdapter | None = None,
        goal_history: GoalHistoryStore | None = None,
        goal_runtime: GoalRuntime | None = None,
        task_service: TaskService | None = None,
        proactive_engine: ProactiveEngine | None = None,
        proactive_policy: ProactivePolicy | None = None,
        proactive_sink: Callable[[ProactiveDecision], None] | None = None,
    ) -> None:
        """Initialize the agent pipeline."""
        self.world = world
        self.contexts = contexts
        self.intents = intents
        self.entity_resolver = entity_resolver
        self.planner = planner
        self.safety = safety
        self.executor = executor
        self.situation_analyzer = situation_analyzer
        self.preference_store = preference_store
        self.context_fusion = context_fusion
        self.goal_runtime = goal_runtime or (
            GoalRuntime(
                resolver=goal_resolver,
                completion=goal_completion,
                plan_adapter=goal_plan_adapter,
                history=goal_history,
                preferences=preference_store,
            )
            if goal_resolver is not None
            else None
        )
        self.task_service = task_service
        self.proactive_engine = proactive_engine
        self.proactive_policy = proactive_policy
        self.proactive_sink = proactive_sink
        self.confirmation_seconds = max(10, confirmation_seconds)
        self.query_responses = QueryResponseBuilder()
        self.action_responses = ActionResponseBuilder()
        self.logger = logging.getLogger(__name__)
        self._request_lock = RLock()
        self._last_proactive_snapshot: str | None = None
        self._active_proactive_signals: set[str] = set()

    def handle(
        self,
        message: str,
        request: AgentRequestContext,
    ) -> AgentResponse:
        """Serialize context and house-state decisions across chat surfaces."""
        with self._request_lock:
            return self._handle_serialized(message, request)

    def _handle_serialized(
        self,
        message: str,
        request: AgentRequestContext,
    ) -> AgentResponse:
        """Handle one request or decline free conversation cleanly."""
        context = self.contexts.get(request)
        snapshot = self.world.snapshot
        catalog = (
            EntityCatalog.from_snapshot(snapshot)
            if snapshot is not None
            else EntityCatalog([])
        )
        if self.task_service is not None and self.task_service.is_task_request(message):
            return self._create_task(message, context)
        fused = self._fuse_context(
            message=message,
            request=request,
            context=context,
            catalog=catalog,
            snapshot=snapshot,
        )
        resolution = self.intents.resolve(message, context, catalog)
        intent = resolution.intent
        self.logger.info(
            "Agent intent: conversation=%s provider=%s kind=%s action=%s "
            "workflow=%s confidence=%.2f",
            context.conversation_id,
            resolution.provider,
            intent.kind,
            intent.action,
            intent.workflow,
            intent.confidence,
        )

        if intent.kind is IntentKind.CONVERSATION:
            return AgentResponse(handled=False, intent=intent)
        if intent.kind is IntentKind.CANCEL:
            if context.pending_plan is not None:
                pending_plan = context.pending_plan
                self.contexts.clear_pending(context)
                if self.goal_runtime is not None:
                    self.goal_runtime.record_plan(
                        pending_plan,
                        context,
                        status=GoalStatus.CANCELLED,
                        result="cancelled_by_user",
                    )
                return AgentResponse(
                    True,
                    "Okay, der ausstehende Plan ist verworfen.",
                    intent,
                )
            if context.pending_task_id is not None and self.task_service is not None:
                task_id = context.pending_task_id
                self.task_service.cancel(task_id)
                self.contexts.clear_pending_task(context)
                return AgentResponse(
                    handled=True,
                    response="Okay, die ausstehende Aufgabe ist verworfen.",
                    intent=intent,
                    task_id=task_id,
                )
            if context.pending_plan is None:
                return AgentResponse(
                    True,
                    "Es gibt keinen ausstehenden Plan oder Task.",
                    intent,
                )
        if intent.kind is IntentKind.CONFIRM and context.pending_plan is None:
            if context.pending_task_id is not None:
                return self._confirm_task(intent, request, context)
            return self._confirm(message, intent, request, context, catalog)
        snapshot = self.world.refresh()
        catalog = (
            EntityCatalog.from_snapshot(snapshot)
            if snapshot is not None
            else EntityCatalog([])
        )
        if snapshot is None or not self.world.last_refresh_ok:
            if intent.kind is IntentKind.QUERY:
                return AgentResponse(
                    True,
                    "Ich kann Home Assistant gerade nicht erreichen; ein alter Wert "
                    "waere nicht verlaesslich.",
                    intent,
                )
            return AgentResponse(
                True,
                "Ich kann Home Assistant gerade nicht erreichen und fuehre nichts aus.",
                intent,
            )
        fused = self._fuse_context(
            message=message,
            request=request,
            context=context,
            catalog=catalog,
            snapshot=snapshot,
            intent=intent,
            observe_proactive=True,
        )
        if intent.kind is IntentKind.CONFIRM:
            return self._confirm(message, intent, request, context, catalog)
        if intent.confidence < 0.55:
            return AgentResponse(
                True,
                (
                    "Ich verstehe das Ziel noch nicht sicher genug. "
                    "Was genau soll passieren?"
                ),
                intent,
            )
        if intent.kind is IntentKind.QUERY:
            return self._query(intent, context, catalog)
        if intent.kind in {IntentKind.ACTION, IntentKind.WORKFLOW}:
            goal: Goal | None = None
            preferences: dict[str, Any] = {}
            if fused is not None and self.goal_runtime is not None:
                goal_context = self.goal_runtime.resolve(
                    message,
                    intent,
                    context,
                    fused.situation,
                )
                if goal_context is not None:
                    goal = goal_context.goal
                    preferences = goal_context.preferences
                    fused = self._fuse_context(
                        message=message,
                        request=request,
                        context=context,
                        catalog=catalog,
                        snapshot=snapshot,
                        intent=intent,
                        goal=goal,
                        preferences=preferences,
                    )
            return self._plan_and_execute(
                message,
                intent,
                context,
                catalog,
                goal=goal,
                preferences=preferences,
                fused_context=fused,
            )
        return AgentResponse(handled=False, intent=intent)

    def _create_task(
        self,
        message: str,
        context: ConversationContext,
    ) -> AgentResponse:
        """Create a conditional task without executing its deferred action."""
        assert self.task_service is not None
        snapshot = self.world.refresh()
        if snapshot is None or not self.world.last_refresh_ok:
            return AgentResponse(
                handled=True,
                response=(
                    "Ich kann Home Assistant gerade nicht verlaesslich lesen und "
                    "speichere deshalb keinen unsicheren Task."
                ),
            )
        catalog = EntityCatalog.from_snapshot(snapshot)
        result = self.task_service.create(message, context, catalog)
        task = result.task
        if task is not None and result.needs_confirmation:
            if context.pending_plan is not None:
                self.contexts.clear_pending(context)
            if context.pending_task_id is not None:
                self.task_service.cancel(context.pending_task_id)
                self.contexts.clear_pending_task(context)
            self.contexts.set_pending_task(context, task.id)
        return AgentResponse(
            handled=result.handled,
            response=result.message,
            needs_confirmation=result.needs_confirmation,
            task_id=task.id if task is not None else None,
        )

    def _confirm_task(
        self,
        intent: AgentIntent,
        request: AgentRequestContext,
        context: ConversationContext,
    ) -> AgentResponse:
        """Activate a reviewed task while preserving owner/channel boundaries."""
        task_id = context.pending_task_id
        if task_id is None or self.task_service is None:
            return AgentResponse(True, "Es gibt keinen ausstehenden Task.", intent)
        if request.user != context.pending_task_user:
            return AgentResponse(
                handled=True,
                response=(
                    "Dieser Task wartet auf die Bestaetigung des anfragenden "
                    "Benutzers."
                ),
                intent=intent,
                needs_confirmation=True,
                task_id=task_id,
            )
        if request.source != context.pending_task_source:
            return AgentResponse(
                handled=True,
                response=(
                    "Dieser Task muss ueber denselben Anfragekanal bestaetigt werden."
                ),
                intent=intent,
                needs_confirmation=True,
                task_id=task_id,
            )
        task = self.task_service.confirm(task_id)
        if task is None:
            self.contexts.clear_pending_task(context)
            return AgentResponse(
                True,
                "Der Task ist nicht mehr bestaetigbar.",
                intent,
                task_id=task_id,
            )
        self.contexts.clear_pending_task(context)
        return AgentResponse(
            handled=True,
            response=(
                f"Aufgabe {task.id[:8]} ist aktiviert. Sie wird erst beim "
                "gespeicherten Ausloeser ausgefuehrt."
            ),
            intent=intent,
            task_id=task.id,
        )

    def _query(
        self,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> AgentResponse:
        resolution = self.entity_resolver.resolve(intent, context, catalog)
        response = self.query_responses.build(intent, resolution)
        entity_ids = [entity.entity_id for entity in resolution.matches]
        self.contexts.remember(
            context,
            intent=intent,
            entity_ids=entity_ids,
            room=intent.room,
        )
        return AgentResponse(
            True,
            response,
            intent,
            tuple(entity_ids),
        )

    def _plan_and_execute(
        self,
        message: str,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
        *,
        goal: Goal | None = None,
        preferences: dict[str, Any] | None = None,
        fused_context: FusedContext | None = None,
    ) -> AgentResponse:
        preferences = preferences or {}
        if context.pending_plan is not None:
            self.logger.info(
                "Superseding pending agent plan: conversation=%s plan=%s",
                context.conversation_id,
                context.pending_plan.id,
            )
            self.contexts.clear_pending(context)
        if goal is not None:
            assert self.goal_runtime is not None
            self.goal_runtime.record(
                goal,
                context,
                status=GoalStatus.REQUESTED,
            )
            completion = self.goal_runtime.completion(
                goal,
                context,
                catalog,
                preferences,
            )
            if (
                completion is not None
                and completion.completed
                and completion.confidence >= 0.75
            ):
                self.contexts.remember(
                    context,
                    intent=intent,
                    entity_ids=completion.entity_ids,
                    room=goal.room,
                )
                self.goal_runtime.record(
                    goal,
                    context,
                    status=GoalStatus.COMPLETED,
                    result="already_complete",
                )
                return AgentResponse(
                    handled=True,
                    response=self.goal_runtime.completed_message(goal),
                    intent=intent,
                    entity_ids=tuple(completion.entity_ids),
                    goal_id=goal.id,
                    goal_completed=True,
                )
        effective_intent = (
            self.goal_runtime.effective_intent(intent, goal)
            if self.goal_runtime is not None
            else intent
        )
        planning = self.planner.plan(
            effective_intent,
            context,
            catalog,
            fused_context=fused_context,
            goal=goal,
            preferences=preferences,
        )
        if planning.plan is None:
            if goal is not None:
                assert self.goal_runtime is not None
                self.goal_runtime.record(
                    goal,
                    context,
                    status=GoalStatus.FAILED,
                    result=planning.message,
                )
            return AgentResponse(True, planning.message, intent)
        plan = planning.plan
        if goal is not None:
            assert self.goal_runtime is not None
            plan = self.goal_runtime.prepare_plan(
                plan,
                goal=goal,
                intent=effective_intent,
                preferences=preferences,
                catalog=catalog,
            )
        self.logger.info(
            "Agent plan: id=%s goal=%s steps=%s",
            plan.id,
            plan.goal,
            [
                {
                    "service": f"{step.domain}.{step.service}",
                    "entities": step.entity_ids,
                    "reason": step.reason,
                }
                for step in plan.steps
            ],
        )
        review = self.safety.review(plan, catalog)
        if review.decision is PermissionDecision.BLOCK:
            if goal is not None:
                assert self.goal_runtime is not None
                self.goal_runtime.record(
                    goal,
                    context,
                    status=GoalStatus.FAILED,
                    plan_id=plan.id,
                    result=review.reasons[0] if review.reasons else "blocked",
                )
            return AgentResponse(
                True,
                self._blocked_response(review.reasons),
                intent,
                tuple(planning.entity_ids),
                plan.id,
                goal_id=goal.id if goal is not None else None,
            )
        self.contexts.remember(
            context,
            intent=intent,
            entity_ids=planning.entity_ids,
            room=planning.room,
        )
        if review.decision is PermissionDecision.REQUIRE_CONFIRM:
            expires_at = datetime.now(UTC) + timedelta(
                seconds=self.confirmation_seconds
            )
            pending = plan.model_copy(update={"expires_at": expires_at})
            self.contexts.set_pending(context, pending)
            if goal is not None:
                assert self.goal_runtime is not None
                self.goal_runtime.record(
                    goal,
                    context,
                    status=GoalStatus.PLANNED,
                    plan_id=pending.id,
                    result="awaiting_confirmation",
                )
            names = {
                entity_id: entity.name for entity_id, entity in catalog.by_id.items()
            }
            return AgentResponse(
                True,
                self.action_responses.confirmation(
                    pending,
                    entity_names=plan_entity_names(pending, names),
                ),
                intent,
                tuple(planning.entity_ids),
                pending.id,
                True,
                goal.id if goal is not None else None,
            )
        if goal is not None:
            assert self.goal_runtime is not None
            self.goal_runtime.record(
                goal,
                context,
                status=GoalStatus.PLANNED,
                plan_id=plan.id,
            )
        return self._execute(
            message,
            plan,
            effective_intent,
            context,
            catalog,
            goal=goal,
            preferences=preferences,
        )

    def _confirm(
        self,
        message: str,
        intent: AgentIntent,
        request: AgentRequestContext,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> AgentResponse:
        plan = context.pending_plan
        if plan is None:
            return AgentResponse(True, "Es gibt keinen ausstehenden Plan.", intent)
        if request.user != context.pending_user:
            return AgentResponse(
                True,
                "Dieser Plan wartet auf die Bestaetigung des anfragenden Benutzers.",
                intent,
                plan_id=plan.id,
                needs_confirmation=True,
            )
        if request.source != context.pending_source:
            return AgentResponse(
                True,
                "Dieser Plan muss ueber denselben Anfragekanal bestaetigt werden.",
                intent,
                plan_id=plan.id,
                needs_confirmation=True,
            )
        if plan.expires_at is not None and datetime.now(UTC) > plan.expires_at:
            self.contexts.clear_pending(context)
            return AgentResponse(
                True,
                "Die Bestaetigung ist abgelaufen. Bitte formuliere den Wunsch erneut.",
                intent,
            )
        review = self.safety.review(plan, catalog)
        if review.decision is PermissionDecision.BLOCK:
            self.contexts.clear_pending(context)
            if self.goal_runtime is not None:
                self.goal_runtime.record_plan(
                    plan,
                    context,
                    status=GoalStatus.FAILED,
                    result=review.reasons[0] if review.reasons else "blocked",
                )
            return AgentResponse(
                True,
                self._blocked_response(review.reasons),
                intent,
                plan_id=plan.id,
                goal_id=plan.goal_id,
            )
        goal = (
            self.goal_runtime.from_plan(plan) if self.goal_runtime is not None else None
        )
        preferences = (
            self.goal_runtime.preferences(goal, context)
            if self.goal_runtime is not None and goal is not None
            else {}
        )
        self.contexts.clear_pending(context)
        return self._execute(
            message,
            plan,
            intent,
            context,
            catalog,
            goal=goal,
            preferences=preferences,
        )

    def _execute(
        self,
        message: str,
        plan: ActionPlan,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
        *,
        goal: Goal | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> AgentResponse:
        execution = self.executor.execute(plan, catalog, user_text=message)
        names = {entity_id: entity.name for entity_id, entity in catalog.by_id.items()}
        entity_ids = list(
            dict.fromkeys(
                entity_id
                for step in execution.plan.steps
                for entity_id in step.entity_ids
            )
        )
        room = next(
            (
                catalog.by_id[entity_id].room
                for entity_id in entity_ids
                if entity_id in catalog.by_id and catalog.by_id[entity_id].room
            ),
            None,
        )
        self.contexts.remember(
            context,
            intent=intent,
            entity_ids=entity_ids,
            room=room,
        )
        completion = None
        if goal is not None and execution.ok:
            refreshed = self.world.refresh()
            if refreshed is not None and self.world.last_refresh_ok:
                assert self.goal_runtime is not None
                completion = self.goal_runtime.completion(
                    goal,
                    context,
                    EntityCatalog.from_snapshot(refreshed),
                    preferences or {},
                )
        goal_completed = bool(
            completion is not None
            and completion.completed
            and completion.confidence >= 0.75
        )
        if goal is not None:
            assert self.goal_runtime is not None
            self.goal_runtime.record(
                goal,
                context,
                status=(
                    GoalStatus.COMPLETED
                    if goal_completed
                    else GoalStatus.PLANNED if execution.ok else GoalStatus.FAILED
                ),
                plan_id=plan.id,
                result=(
                    "goal_completed"
                    if goal_completed
                    else "completion_pending" if execution.ok else "execution_failed"
                ),
            )
        response = self.action_responses.execution(execution, entity_names=names)
        if goal_completed:
            response = f"{response} Ziel erreicht."
        return AgentResponse(
            handled=True,
            response=response,
            intent=intent,
            entity_ids=tuple(entity_ids),
            plan_id=execution.plan.id,
            goal_id=goal.id if goal is not None else plan.goal_id,
            goal_completed=goal_completed,
        )

    def _blocked_response(self, reasons: tuple[str, ...]) -> str:
        reason = reasons[0] if reasons else "unbekannt"
        if reason == "service_registry_unavailable":
            return (
                "Ich kann den Plan gerade nicht sicher gegen Home Assistants "
                "Servicekatalog pruefen. Deshalb fuehre ich nichts aus."
            )
        if reason.startswith("unknown_entity"):
            return "Die geplante Entity existiert nicht mehr. Ich fuehre nichts aus."
        if reason.startswith("unavailable_entity"):
            return "Das Zielgeraet ist nicht verfuegbar. Ich fuehre nichts aus."
        if reason.startswith("unknown_service"):
            return "Home Assistant bietet den geplanten Service nicht an."
        if reason.startswith("unsupported_"):
            return "Das Geraet unterstuetzt die gewuenschte Funktion nicht."
        if reason.startswith(
            (
                "invalid_",
                "reserved_parameter",
                "conflicting_",
            )
        ):
            return "Der geplante Wert ist fuer dieses Geraet nicht zulaessig."
        return "Der Plan wurde von Kiras Sicherheitspruefung blockiert."

    def _fuse_context(
        self,
        *,
        message: str,
        request: AgentRequestContext,
        context: ConversationContext,
        catalog: EntityCatalog,
        snapshot: HomeAssistantWorldSnapshot | None,
        intent: AgentIntent | None = None,
        goal: BaseModel | None = None,
        preferences: dict[str, Any] | None = None,
        observe_proactive: bool = False,
    ) -> FusedContext | None:
        """Attach semantic situation context when all optional layers exist."""
        if (
            snapshot is None
            or self.situation_analyzer is None
            or self.context_fusion is None
        ):
            return None
        recent_goals = (
            self.goal_runtime.recent_context(context)
            if self.goal_runtime is not None
            else []
        )
        situation = self.situation_analyzer.analyze(
            snapshot,
            catalog,
            request,
            recent_goals=tuple(str(item["type"]) for item in recent_goals),
        )
        if observe_proactive:
            self._observe_proactive(situation)
        return self.context_fusion.fuse(
            request=request,
            conversation=context,
            situation=situation,
            catalog=catalog,
            message=message,
            intent=intent,
            goal=goal,
            recent_goals=recent_goals,
            preferences=preferences,
        )

    def _observe_proactive(self, situation: SituationContext) -> None:
        """Evaluate each fresh situation once without executing any action."""
        if self.proactive_engine is None or self.proactive_policy is None:
            return
        updated_at = situation.updated_at
        if self._last_proactive_snapshot == updated_at:
            return
        self._last_proactive_snapshot = updated_at
        signals = self.proactive_engine.detect(situation)
        active_keys = {signal.key for signal in signals}
        new_keys = active_keys - self._active_proactive_signals
        self._active_proactive_signals = active_keys
        if signals:
            self.logger.info(
                "Proactive observations: active=%s new=%s mode=%s",
                len(signals),
                len(new_keys),
                self.proactive_policy.mode,
            )
        for signal in signals:
            decision = self.proactive_policy.decide(signal)
            self.logger.debug(
                "Proactive signal: key=%s confidence=%.2f policy=%s",
                signal.key,
                signal.confidence,
                decision.reason,
            )
            if (
                signal.key in new_keys
                and decision.notify
                and self.proactive_sink is not None
            ):
                self.proactive_sink(decision)
