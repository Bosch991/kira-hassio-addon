"""Coordinate the context-aware Home Assistant agent pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

from kira.agent.context import ConversationContextStore
from kira.agent.entities import EntityCatalog, EntityResolver
from kira.agent.execution import ActionExecutor
from kira.agent.intents import IntentResolver
from kira.agent.models import (
    ActionPlan,
    AgentIntent,
    AgentRequestContext,
    ConversationContext,
    IntentKind,
)
from kira.agent.planning import HomeAssistantPlanner
from kira.agent.responses import (
    ActionResponseBuilder,
    QueryResponseBuilder,
    plan_entity_names,
)
from kira.agent.safety import PlanSafetyManager
from kira.homeassistant.permissions import PermissionDecision
from kira.homeassistant.world_model import HomeAssistantWorldModel


@dataclass(frozen=True, slots=True)
class AgentResponse:
    """Result returned to a chat surface by the HA agent."""

    handled: bool
    response: str = ""
    intent: AgentIntent | None = None
    entity_ids: tuple[str, ...] = ()
    plan_id: str | None = None
    needs_confirmation: bool = False


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
    ) -> None:
        """Initialize the agent pipeline."""
        self.world = world
        self.contexts = contexts
        self.intents = intents
        self.entity_resolver = entity_resolver
        self.planner = planner
        self.safety = safety
        self.executor = executor
        self.confirmation_seconds = max(10, confirmation_seconds)
        self.query_responses = QueryResponseBuilder()
        self.action_responses = ActionResponseBuilder()
        self.logger = logging.getLogger(__name__)
        self._request_lock = RLock()

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
            if context.pending_plan is None:
                return AgentResponse(
                    True,
                    "Es gibt keinen ausstehenden Plan.",
                    intent,
                )
            self.contexts.clear_pending(context)
            return AgentResponse(
                True,
                "Okay, der ausstehende Plan ist verworfen.",
                intent,
            )
        if intent.kind is IntentKind.CONFIRM and context.pending_plan is None:
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
            return self._plan_and_execute(message, intent, context, catalog)
        return AgentResponse(handled=False, intent=intent)

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
    ) -> AgentResponse:
        if context.pending_plan is not None:
            self.logger.info(
                "Superseding pending agent plan: conversation=%s plan=%s",
                context.conversation_id,
                context.pending_plan.id,
            )
            self.contexts.clear_pending(context)
        planning = self.planner.plan(intent, context, catalog)
        if planning.plan is None:
            return AgentResponse(True, planning.message, intent)
        self.logger.info(
            "Agent plan: id=%s goal=%s steps=%s",
            planning.plan.id,
            planning.plan.goal,
            [
                {
                    "service": f"{step.domain}.{step.service}",
                    "entities": step.entity_ids,
                    "reason": step.reason,
                }
                for step in planning.plan.steps
            ],
        )
        review = self.safety.review(planning.plan, catalog)
        if review.decision is PermissionDecision.BLOCK:
            return AgentResponse(
                True,
                self._blocked_response(review.reasons),
                intent,
                tuple(planning.entity_ids),
                planning.plan.id,
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
            pending = planning.plan.model_copy(update={"expires_at": expires_at})
            self.contexts.set_pending(context, pending)
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
            )
        return self._execute(message, planning.plan, intent, context, catalog)

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
            return AgentResponse(
                True,
                self._blocked_response(review.reasons),
                intent,
                plan_id=plan.id,
            )
        self.contexts.clear_pending(context)
        return self._execute(message, plan, intent, context, catalog)

    def _execute(
        self,
        message: str,
        plan: ActionPlan,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
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
        return AgentResponse(
            True,
            self.action_responses.execution(execution, entity_names=names),
            intent,
            tuple(entity_ids),
            execution.plan.id,
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
