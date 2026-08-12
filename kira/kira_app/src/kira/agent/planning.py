"""Build direct Home Assistant action plans from resolved intents."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from kira.agent.entities import EntityCatalog, EntityResolver
from kira.agent.models import (
    ActionPlan,
    ActionType,
    AgentIntent,
    ConversationContext,
    PlanStep,
    SelectionMode,
)
from kira.agent.workflows import WorkflowEngine, action_service


class PlanningResult(BaseModel):
    """Result of direct or workflow plan construction."""

    model_config = ConfigDict(extra="forbid")

    plan: ActionPlan | None = None
    entity_ids: list[str] = Field(default_factory=list)
    room: str | None = None
    message: str = ""


class HomeAssistantPlanner:
    """Create typed plans from abstract intents and current entities."""

    def __init__(
        self,
        *,
        entity_resolver: EntityResolver,
        workflow_engine: WorkflowEngine,
    ) -> None:
        """Initialize planner dependencies."""
        self.entity_resolver = entity_resolver
        self.workflow_engine = workflow_engine

    def plan(
        self,
        intent: AgentIntent,
        context: ConversationContext,
        catalog: EntityCatalog,
    ) -> PlanningResult:
        """Create a plan or return the smallest useful clarification."""
        if intent.workflow:
            workflow = self.workflow_engine.plan(intent, context, catalog)
            room = intent.room or context.source_room or context.previous_room
            return PlanningResult(
                plan=workflow.plan,
                entity_ids=workflow.matched_entity_ids,
                room=room,
                message=workflow.message,
            )

        resolution = self.entity_resolver.resolve(intent, context, catalog)
        if resolution.ambiguous:
            names = ", ".join(
                candidate.entity.name for candidate in resolution.candidates[:4]
            )
            return PlanningResult(
                message=(
                    f"Ich finde mehrere passende Geraete: {names}. "
                    "Welches meinst du?"
                )
            )
        if not resolution.matches:
            target = intent.target or "das Geraet"
            return PlanningResult(
                message=(
                    f"Ich finde fuer '{target}' keine erreichbare, passende Entity."
                )
            )

        matches = list(resolution.matches)
        domains = {entity.domain for entity in matches}
        if len(domains) != 1:
            if intent.selection is not SelectionMode.ALL or intent.action not in {
                ActionType.TURN_ON,
                ActionType.TURN_OFF,
                ActionType.TOGGLE,
            }:
                return PlanningResult(
                    message="Die passenden Geraete brauchen unterschiedliche Aktionen."
                )
            steps: list[PlanStep] = []
            for domain in sorted(domains):
                domain_matches = [
                    entity for entity in matches if entity.domain == domain
                ]
                service, data, expected_states = action_service(
                    intent,
                    domain_matches,
                )
                if service is None:
                    return PlanningResult(
                        message=(
                            "Mindestens ein gefundenes Geraet unterstuetzt diese "
                            "Sammelaktion nicht."
                        )
                    )
                steps.append(
                    PlanStep(
                        domain=domain,
                        service=service,
                        entity_ids=[entity.entity_id for entity in domain_matches],
                        data=data,
                        expected_states=expected_states,
                        reason=intent.rationale
                        or "Bereichsuebergreifendes Benutzerziel",
                    )
                )
            return PlanningResult(
                plan=ActionPlan(
                    goal=intent.goal,
                    intent=f"multi_domain.{intent.action}",
                    steps=steps,
                    explanation=(
                        "Mehrere aktuelle Geraetetypen als einen Plan behandeln."
                    ),
                ),
                entity_ids=[entity.entity_id for entity in matches],
                room=intent.room,
            )
        service, data, expected_states = action_service(intent, matches)
        if service is None:
            return PlanningResult(
                message="Das gefundene Geraet unterstuetzt diese Aktion nicht."
            )
        step = PlanStep(
            domain=matches[0].domain,
            service=service,
            entity_ids=[entity.entity_id for entity in matches],
            data=data,
            expected_states=expected_states,
            reason=intent.rationale or "Direktes Benutzerziel",
        )
        return PlanningResult(
            plan=ActionPlan(
                goal=intent.goal,
                intent=f"{matches[0].domain}.{service}",
                steps=[step],
                explanation=(
                    f"{len(matches)} passende Entity"
                    f"{'s' if len(matches) != 1 else ''} aus dem Live-Zustand gewaehlt."
                ),
            ),
            entity_ids=[entity.entity_id for entity in matches],
            room=intent.room or matches[0].room,
        )
