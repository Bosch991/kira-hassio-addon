"""Fuse bounded conversation, situation, goal, preference, and entity context."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kira.agent.entities import EntityCatalog, EntityDescriptor
from kira.agent.models import AgentIntent, AgentRequestContext, ConversationContext
from kira.agent.normalization import normalize_text, text_tokens
from kira.agent.situation import ConfidenceValue, SituationContext


class FusedContext(BaseModel):
    """Compact, relevant context shared by intent and planning layers."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    user: str | None = None
    timestamp: str
    resolved_room: ConfidenceValue | None = None
    conversation: dict[str, Any] = Field(default_factory=dict)
    situation: SituationContext
    goal: dict[str, Any] | None = None
    recent_goals: list[dict[str, Any]] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)
    relevant_entities: list[dict[str, Any]] = Field(default_factory=list)

    def compact(self) -> dict[str, Any]:
        """Return the model-facing representation without full HA state."""
        return {
            "conversation_id": self.conversation_id,
            "user": self.user,
            "timestamp": self.timestamp,
            "resolved_room": (
                self.resolved_room.model_dump(mode="json")
                if self.resolved_room is not None
                else None
            ),
            "conversation": self.conversation,
            "situation": self.situation.compact(),
            "goal": self.goal,
            "recent_goals": self.recent_goals,
            "preferences": self.preferences,
            "relevant_entities": self.relevant_entities,
        }


class ContextFusionEngine:
    """Select and combine only context relevant to the current request."""

    def __init__(self, *, entity_limit: int = 50) -> None:
        """Initialize the hard model-context entity bound."""
        self.entity_limit = max(10, entity_limit)

    def fuse(
        self,
        *,
        request: AgentRequestContext,
        conversation: ConversationContext,
        situation: SituationContext,
        catalog: EntityCatalog,
        message: str,
        intent: AgentIntent | None = None,
        goal: BaseModel | None = None,
        recent_goals: list[dict[str, Any]] | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> FusedContext:
        """Build a bounded context and attach it to the entity catalog."""
        goal_payload = goal.model_dump(mode="json") if goal is not None else None
        resolved_room = self._resolve_room(
            request=request,
            conversation=conversation,
            situation=situation,
            intent=intent,
            goal_payload=goal_payload,
        )
        relevant = self._relevant_entities(
            catalog,
            message=message,
            conversation=conversation,
            resolved_room=resolved_room,
            intent=intent,
            goal_payload=goal_payload,
        )
        fused = FusedContext(
            conversation_id=conversation.conversation_id,
            user=request.user or conversation.user,
            timestamp=request.timestamp.isoformat(),
            resolved_room=resolved_room,
            conversation={
                "source": conversation.source,
                "source_device": conversation.source_device,
                "source_room": conversation.source_room,
                "previous_room": conversation.previous_room,
                "previous_entities": conversation.previous_entities,
                "previous_action": str(conversation.previous_action),
                "has_pending_plan": conversation.pending_plan is not None,
                "has_pending_task": conversation.pending_task_id is not None,
            },
            situation=situation,
            goal=goal_payload,
            recent_goals=list(recent_goals or [])[:5],
            preferences=dict(preferences or {}),
            relevant_entities=[self._entity_context(item) for item in relevant],
        )
        catalog.semantic_context = fused.compact()
        return fused

    def _resolve_room(
        self,
        *,
        request: AgentRequestContext,
        conversation: ConversationContext,
        situation: SituationContext,
        intent: AgentIntent | None,
        goal_payload: dict[str, Any] | None,
    ) -> ConfidenceValue | None:
        if request.source_room:
            return ConfidenceValue(
                value=request.source_room,
                confidence=0.99,
                source="assist_source",
                evidence=[f"source_room={request.source_room}"],
            )
        if intent is not None and intent.room:
            return ConfidenceValue(
                value=intent.room,
                confidence=max(0.85, intent.confidence),
                source="user_request",
                evidence=[f"intent_room={intent.room}"],
            )
        if goal_payload and goal_payload.get("room"):
            return ConfidenceValue(
                value=str(goal_payload["room"]),
                confidence=float(goal_payload.get("confidence", 0.8)),
                source="goal",
                evidence=[f"goal_room={goal_payload['room']}"],
            )
        if conversation.previous_room:
            return ConfidenceValue(
                value=conversation.previous_room,
                confidence=0.76,
                source="conversation",
                evidence=[f"previous_room={conversation.previous_room}"],
            )
        return situation.active_room

    def _relevant_entities(
        self,
        catalog: EntityCatalog,
        *,
        message: str,
        conversation: ConversationContext,
        resolved_room: ConfidenceValue | None,
        intent: AgentIntent | None,
        goal_payload: dict[str, Any] | None,
    ) -> list[EntityDescriptor]:
        scores: dict[str, float] = {}
        message_tokens = text_tokens(message)
        target_tokens = (
            text_tokens(intent.target or "") if intent is not None else set()
        )
        goal_type = normalize_text(str((goal_payload or {}).get("type", "")))
        room = normalize_text(resolved_room.value) if resolved_room is not None else ""
        for entity in catalog.entities:
            score = 0.0
            if entity.entity_id in conversation.previous_entities:
                score += 100
            if room and entity.room and normalize_text(entity.room) == room:
                score += 35 * (resolved_room.confidence if resolved_room else 1.0)
            entity_tokens = text_tokens(entity.search_text)
            score += len(message_tokens & entity_tokens) * 5
            score += len(target_tokens & entity_tokens) * 8
            if goal_type and (
                goal_type in {normalize_text(item) for item in entity.used_for}
                or any(token in entity.search_text for token in text_tokens(goal_type))
            ):
                score += 24
            if entity.state in {"on", "playing", "active", "running"}:
                score += 3
            if not entity.available:
                score += 1
            if entity.domain in {"scene", "script", "automation"}:
                score += 4
            if score:
                scores[entity.entity_id] = score
        selected_ids = [
            entity_id
            for entity_id, _score in sorted(
                scores.items(),
                key=lambda item: (-item[1], item[0]),
            )[: self.entity_limit]
        ]
        for entity_id in list(selected_ids):
            entity = catalog.by_id.get(entity_id)
            if entity is None:
                continue
            for related_id in entity.related_entity_ids:
                if related_id in catalog.by_id and related_id not in selected_ids:
                    selected_ids.append(related_id)
                    if len(selected_ids) >= self.entity_limit:
                        break
            if len(selected_ids) >= self.entity_limit:
                break
        if not selected_ids:
            selected_ids = [
                item.entity_id
                for item in sorted(catalog.entities, key=lambda item: item.entity_id)[
                    : self.entity_limit
                ]
            ]
        return [catalog.by_id[entity_id] for entity_id in selected_ids]

    def _entity_context(self, entity: EntityDescriptor) -> dict[str, Any]:
        return {
            "entity_id": entity.entity_id,
            "name": entity.name,
            "domain": entity.domain,
            "state": entity.state,
            "room": entity.room,
            "area_id": entity.area_id,
            "area_confidence": entity.area_confidence,
            "area_source": entity.area_source,
            "device_id": entity.device_id,
            "device_class": entity.device_class,
            "capabilities": sorted(entity.capabilities),
            "used_for": list(entity.used_for),
            "related_entity_ids": list(entity.related_entity_ids),
            "aliases": list(entity.aliases),
        }
