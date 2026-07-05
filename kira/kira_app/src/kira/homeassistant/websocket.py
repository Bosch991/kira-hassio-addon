"""Home Assistant websocket live event client."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from kira.homeassistant.events import (
    HomeAssistantEventFilter,
    HomeAssistantEventParser,
    HomeAssistantEventStore,
    HomeAssistantLiveEvent,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_EVENT_TYPES = (
    "state_changed",
    "call_service",
    "automation_triggered",
    "homeassistant_started",
    "homeassistant_stop",
)


class HomeAssistantLiveStatus(StrEnum):
    """Lifecycle states for the live websocket client."""

    STOPPED = "stopped"
    CONNECTING = "connecting"
    RUNNING = "running"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class HomeAssistantLiveState:
    """Public status snapshot for live mode."""

    status: HomeAssistantLiveStatus
    connected: bool
    subscribed_events: tuple[str, ...]
    stored_events: int
    last_error: str | None = None


class HomeAssistantLiveClient:
    """Read-only websocket client for Home Assistant events."""

    def __init__(
        self,
        *,
        base_url: str | None,
        token: str | None,
        event_store: HomeAssistantEventStore,
        event_filter: HomeAssistantEventFilter,
        timeout: float = 20.0,
        reconnect_delay: float = 5.0,
        notifications_enabled: bool = False,
        event_types: tuple[str, ...] = DEFAULT_EVENT_TYPES,
        connect_fn: Callable[..., Any] | None = None,
    ) -> None:
        """Initialize the live client."""
        self.base_url = base_url.rstrip("/") if base_url else None
        self.token = token
        self.event_store = event_store
        self.event_filter = event_filter
        self.parser = HomeAssistantEventParser(event_filter)
        self.timeout = timeout
        self.reconnect_delay = reconnect_delay
        self.notifications_enabled = notifications_enabled
        self.event_types = event_types
        self.connect_fn = connect_fn
        self._status = HomeAssistantLiveStatus.STOPPED
        self._connected = False
        self._last_error: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        """Return whether Home Assistant websocket credentials are available."""
        return bool(self.base_url and self.token)

    def start(self) -> HomeAssistantLiveState:
        """Start live event listening in a background thread."""
        self.event_store.initialize()
        if not self.is_configured:
            with self._lock:
                self._status = HomeAssistantLiveStatus.ERROR
                self._last_error = "HOMEASSISTANT_URL or HOMEASSISTANT_TOKEN missing."
            return self.status()

        if self._thread is not None and self._thread.is_alive():
            return self.status()

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_thread,
            name="kira-ha-live",
            daemon=True,
        )
        self._thread.start()
        return self.status()

    def stop(self) -> HomeAssistantLiveState:
        """Stop live event listening."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        with self._lock:
            self._connected = False
            self._status = HomeAssistantLiveStatus.STOPPED
        return self.status()

    def status(self) -> HomeAssistantLiveState:
        """Return a status snapshot."""
        with self._lock:
            return HomeAssistantLiveState(
                status=self._status,
                connected=self._connected,
                subscribed_events=self.event_types,
                stored_events=self.event_store.count(),
                last_error=self._last_error,
            )

    def list_events(self, limit: int = 20) -> list[HomeAssistantLiveEvent]:
        """Return recent stored live events."""
        self.event_store.initialize()
        return self.event_store.list_events(limit=limit)

    def clear_events(self) -> None:
        """Clear recent live events."""
        self.event_store.initialize()
        self.event_store.clear()

    async def listen_once(self) -> None:
        """Run one websocket listening loop until stopped or disconnected."""
        if not self.is_configured:
            raise RuntimeError("Home Assistant live mode is not configured.")

        assert self.base_url is not None
        websocket_url = self._websocket_url()
        connect_fn = self.connect_fn
        if connect_fn is None:
            try:
                from websockets.asyncio.client import connect as connect_fn
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Install websockets for Home Assistant live mode."
                ) from exc

        LOGGER.info("Connecting Home Assistant websocket: %s", websocket_url)
        async with connect_fn(
            websocket_url,
            open_timeout=self.timeout,
            ping_interval=20,
            ping_timeout=20,
        ) as websocket:
            await self._authenticate(websocket)
            await self._subscribe(websocket)
            with self._lock:
                self._connected = True
                self._status = HomeAssistantLiveStatus.RUNNING
                self._last_error = None

            while not self._stop_event.is_set():
                message = await asyncio.wait_for(websocket.recv(), timeout=self.timeout)
                self._handle_message(message)

    def _run_thread(self) -> None:
        with self._lock:
            self._status = HomeAssistantLiveStatus.CONNECTING
            self._last_error = None
        while not self._stop_event.is_set():
            try:
                asyncio.run(self.listen_once())
            except TimeoutError as exc:
                self._record_error(f"Home Assistant websocket timeout: {exc}")
            except Exception as exc:
                self._record_error(str(exc))

            if not self._stop_event.is_set():
                self._stop_event.wait(self.reconnect_delay)

    async def _authenticate(self, websocket: Any) -> None:
        auth_required = json.loads(
            await asyncio.wait_for(websocket.recv(), self.timeout)
        )
        if auth_required.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected websocket greeting: {auth_required}")

        await websocket.send(json.dumps({"type": "auth", "access_token": self.token}))
        auth_result = json.loads(await asyncio.wait_for(websocket.recv(), self.timeout))
        if auth_result.get("type") != "auth_ok":
            raise RuntimeError(f"Home Assistant websocket auth failed: {auth_result}")

    async def _subscribe(self, websocket: Any) -> None:
        for index, event_type in enumerate(self.event_types, start=1):
            await websocket.send(
                json.dumps(
                    {
                        "id": index,
                        "type": "subscribe_events",
                        "event_type": event_type,
                    }
                )
            )
            result = json.loads(await asyncio.wait_for(websocket.recv(), self.timeout))
            if not result.get("success", False):
                raise RuntimeError(f"Subscribe failed for {event_type}: {result}")

    def _handle_message(self, message: str | bytes) -> None:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        payload = json.loads(message)
        if payload.get("type") != "event":
            return
        event = self.parser.parse(payload)
        if event is None:
            return
        if self.event_filter.should_store(event):
            self.event_store.add(event)
            LOGGER.info("Home Assistant live event: %s", event.summary)
            if self.notifications_enabled and event.important:
                LOGGER.info("Live notification candidate: %s", event.summary)

    def _record_error(self, message: str) -> None:
        LOGGER.warning("Home Assistant live client error: %s", message)
        with self._lock:
            self._connected = False
            self._status = HomeAssistantLiveStatus.ERROR
            self._last_error = message

    def _websocket_url(self) -> str:
        assert self.base_url is not None
        if self.base_url == "http://supervisor/core":
            return "ws://supervisor/core/websocket"
        if self.base_url.startswith("https://"):
            return f"wss://{self.base_url.removeprefix('https://')}/api/websocket"
        if self.base_url.startswith("http://"):
            return f"ws://{self.base_url.removeprefix('http://')}/api/websocket"
        return f"ws://{self.base_url}/api/websocket"


def make_live_event(
    *,
    event_type: str,
    summary: str,
    entity_id: str | None = None,
    new_state: str | None = None,
) -> HomeAssistantLiveEvent:
    """Create a live event for tests and future notification previews."""
    domain = entity_id.split(".", maxsplit=1)[0] if entity_id else None
    return HomeAssistantLiveEvent(
        timestamp=datetime.now(UTC).isoformat(),
        event_type=event_type,
        entity_id=entity_id,
        friendly_name=entity_id,
        old_state=None,
        new_state=new_state,
        domain=domain,
        summary=summary,
    )
