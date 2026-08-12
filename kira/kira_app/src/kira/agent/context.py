"""Persistent conversation context for Home Assistant reasoning."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock

from pydantic import ValidationError

from kira.agent.models import (
    ActionPlan,
    AgentIntent,
    AgentRequestContext,
    ConversationContext,
    ConversationContextDocument,
    utc_now,
)


class ConversationContextStore:
    """Persist isolated context for multiple conversations."""

    def __init__(self, path: Path, *, max_contexts: int = 100) -> None:
        """Initialize the store path and retention limit."""
        self.path = path
        self.max_contexts = max_contexts
        self._lock = RLock()
        self.logger = logging.getLogger(__name__)

    def initialize(self) -> None:
        """Create an empty context document when missing."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self._write(ConversationContextDocument())

    def get(self, request: AgentRequestContext) -> ConversationContext:
        """Load context for a request and refresh its origin metadata."""
        with self._lock:
            document = self._read()
            context_id = self.context_id(request)
            context = document.contexts.get(context_id)
            if context is None:
                context = ConversationContext(conversation_id=context_id)
            context.user = request.user or context.user
            context.source = request.source or context.source
            context.source_device = request.source_device or context.source_device
            context.source_room = request.source_room or context.source_room
            context.updated_at = request.timestamp
            return context.model_copy(deep=True)

    def save(self, context: ConversationContext) -> None:
        """Persist one context and prune oldest entries."""
        with self._lock:
            document = self._read()
            context.updated_at = utc_now()
            document.contexts[context.conversation_id] = context.model_copy(deep=True)
            ordered = sorted(
                document.contexts.items(),
                key=lambda item: item[1].updated_at,
                reverse=True,
            )
            document.contexts = dict(ordered[: self.max_contexts])
            self._write(document)

    def remember(
        self,
        context: ConversationContext,
        *,
        intent: AgentIntent,
        entity_ids: list[str],
        room: str | None,
    ) -> ConversationContext:
        """Record the latest resolved intent and entity references."""
        context.previous_intent = intent
        context.previous_action = intent.action
        if entity_ids:
            context.previous_entities = list(dict.fromkeys(entity_ids))
        context.previous_room = room or context.previous_room or context.source_room
        self.save(context)
        return context

    def set_pending(
        self,
        context: ConversationContext,
        plan: ActionPlan,
    ) -> ConversationContext:
        """Store a plan awaiting explicit confirmation."""
        context.pending_plan = plan
        context.pending_user = context.user
        context.pending_source = context.source
        self.save(context)
        return context

    def clear_pending(self, context: ConversationContext) -> ConversationContext:
        """Remove a pending plan from a conversation."""
        context.pending_plan = None
        context.pending_user = None
        context.pending_source = None
        self.save(context)
        return context

    def context_id(self, request: AgentRequestContext) -> str:
        """Return a stable storage key for request metadata."""
        if request.conversation_id:
            return request.conversation_id
        if request.user:
            return f"{request.source}:{request.user}"
        return f"{request.source}:default"

    def _read(self) -> ConversationContextDocument:
        self.initialize()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return ConversationContextDocument.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            self.logger.warning("Agent context could not be loaded: %s", exc)
            document = ConversationContextDocument()
            backup = self.path.with_name(
                f"{self.path.name}.corrupt-{utc_now().strftime('%Y%m%d%H%M%S%f')}"
            )
            try:
                self.path.replace(backup)
                self._write(document)
            except OSError as backup_error:
                self.logger.error(
                    "Agent context recovery could not preserve the bad file: %s",
                    backup_error,
                )
            return document

    def _write(self, document: ConversationContextDocument) -> None:
        payload = document.model_dump(mode="json")
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
