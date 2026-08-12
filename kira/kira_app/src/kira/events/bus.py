"""Synchronous in-process event bus."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from threading import RLock

from kira.events.events import Event

EventHandler = Callable[[Event], None]


class EventBus:
    """Small synchronous publish/subscribe bus for plugins."""

    def __init__(self) -> None:
        """Initialize an empty event bus."""
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._all_handlers: list[EventHandler] = []
        self._events: list[Event] = []
        self._lock = RLock()
        self.logger = logging.getLogger(__name__)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Subscribe a handler to one event name."""
        with self._lock:
            self._handlers[event_name].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe a handler to every event."""
        with self._lock:
            self._all_handlers.append(handler)

    def publish(self, event: Event) -> None:
        """Publish one event to matching handlers."""
        with self._lock:
            self._events.append(event)
            handlers = [*self._handlers[event.name], *self._all_handlers]
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                self.logger.exception("Event handler failed for %s", event.name)

    def recent(self, *, limit: int = 50) -> list[Event]:
        """Return recent events."""
        with self._lock:
            return self._events[-limit:]
