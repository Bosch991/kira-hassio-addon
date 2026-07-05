"""Home Assistant live event parsing, filtering, and storage."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_IGNORED_ENTITY_PATTERNS = (
    "sensor.time",
    "sensor.date",
    "sensor.uptime",
    "sensor.weather",
    "weather.",
    "_battery",
    "battery_",
    "batterie",
)
DEFAULT_IGNORED_DOMAINS = ("sun", "zone")
DEFAULT_IMPORTANT_TERMS = (
    "doorbell",
    "klingel",
    "waschmaschine",
    "washing_machine",
    "drucker",
    "printer",
    "3d",
    "automation",
)
IMPORTANT_EVENT_TYPES = (
    "automation_triggered",
    "homeassistant_started",
    "homeassistant_stop",
)


@dataclass(frozen=True, slots=True)
class HomeAssistantLiveEvent:
    """Normalized event stored by Kira's Home Assistant live mode."""

    timestamp: str
    event_type: str
    entity_id: str | None
    friendly_name: str | None
    old_state: str | None
    new_state: str | None
    domain: str | None
    summary: str
    important: bool = False


@dataclass(frozen=True, slots=True)
class EventFilterConfig:
    """Configurable event filter rules."""

    ignored_entity_patterns: tuple[str, ...] = DEFAULT_IGNORED_ENTITY_PATTERNS
    ignored_domains: tuple[str, ...] = DEFAULT_IGNORED_DOMAINS
    ignored_attribute_only_changes: bool = True
    important_terms: tuple[str, ...] = DEFAULT_IMPORTANT_TERMS


class HomeAssistantEventFilter:
    """Decide whether Home Assistant live events should be stored."""

    def __init__(self, config: EventFilterConfig) -> None:
        """Initialize the filter with parsed configuration."""
        self.config = config

    @classmethod
    def from_file(cls, path: Path) -> HomeAssistantEventFilter:
        """Load event filter rules from a small YAML-like config file."""
        if not path.exists():
            return cls(EventFilterConfig())

        data = _read_simple_yaml(path)
        return cls(
            EventFilterConfig(
                ignored_entity_patterns=tuple(
                    data.get(
                        "ignored_entity_patterns",
                        DEFAULT_IGNORED_ENTITY_PATTERNS,
                    )
                ),
                ignored_domains=tuple(
                    data.get("ignored_domains", DEFAULT_IGNORED_DOMAINS)
                ),
                ignored_attribute_only_changes=bool(
                    data.get("ignored_attribute_only_changes", True)
                ),
                important_terms=tuple(
                    data.get("important_terms", DEFAULT_IMPORTANT_TERMS)
                ),
            )
        )

    def should_store(self, event: HomeAssistantLiveEvent) -> bool:
        """Return whether an event should be persisted."""
        if event.important:
            return True
        if event.domain in self.config.ignored_domains:
            return False
        haystack = self._haystack(event)
        if any(pattern in haystack for pattern in self.config.ignored_entity_patterns):
            return False
        if (
            self.config.ignored_attribute_only_changes
            and event.old_state == event.new_state
            and event.event_type == "state_changed"
        ):
            return False
        return True

    def is_important(self, event: HomeAssistantLiveEvent) -> bool:
        """Return whether Kira should mark an event as important."""
        if event.event_type in IMPORTANT_EVENT_TYPES:
            return True
        if event.new_state in {"unavailable", "unknown"}:
            return True
        if event.domain in {"light", "switch"} and event.old_state != event.new_state:
            return True
        haystack = self._haystack(event)
        return any(term in haystack for term in self.config.important_terms)

    def _haystack(self, event: HomeAssistantLiveEvent) -> str:
        return " ".join(
            value
            for value in (
                event.event_type,
                event.entity_id,
                event.friendly_name,
                event.domain,
                event.summary,
            )
            if value
        ).lower()


class HomeAssistantEventParser:
    """Parse Home Assistant websocket event payloads into stable records."""

    def __init__(self, event_filter: HomeAssistantEventFilter) -> None:
        """Initialize the parser with filter rules for importance detection."""
        self.event_filter = event_filter

    def parse(self, payload: dict[str, Any]) -> HomeAssistantLiveEvent | None:
        """Parse a websocket event message."""
        event = payload.get("event", payload)
        if not isinstance(event, dict):
            return None

        event_type = str(event.get("event_type", payload.get("event_type", "")))
        if not event_type:
            return None
        data = event.get("data", {})
        if not isinstance(data, dict):
            data = {}

        if event_type == "state_changed":
            parsed = self._parse_state_changed(event, data)
        elif event_type == "call_service":
            parsed = self._parse_call_service(event, data)
        elif event_type == "automation_triggered":
            parsed = self._parse_automation(event, data)
        elif event_type in {"homeassistant_started", "homeassistant_stop"}:
            parsed = self._parse_homeassistant_lifecycle(event, event_type)
        else:
            parsed = self._parse_generic(event, event_type, data)

        important = self.event_filter.is_important(parsed)
        return HomeAssistantLiveEvent(
            timestamp=parsed.timestamp,
            event_type=parsed.event_type,
            entity_id=parsed.entity_id,
            friendly_name=parsed.friendly_name,
            old_state=parsed.old_state,
            new_state=parsed.new_state,
            domain=parsed.domain,
            summary=parsed.summary,
            important=important,
        )

    def _parse_state_changed(
        self,
        event: dict[str, Any],
        data: dict[str, Any],
    ) -> HomeAssistantLiveEvent:
        entity_id = _optional_str(data.get("entity_id"))
        old_state_obj = _dict_or_empty(data.get("old_state"))
        new_state_obj = _dict_or_empty(data.get("new_state"))
        old_state = _optional_str(old_state_obj.get("state"))
        new_state = _optional_str(new_state_obj.get("state"))
        attributes = _dict_or_empty(new_state_obj.get("attributes"))
        friendly_name = _optional_str(attributes.get("friendly_name")) or entity_id
        domain = entity_id.split(".", maxsplit=1)[0] if entity_id else None
        summary = self._state_summary(entity_id, friendly_name, old_state, new_state)
        return HomeAssistantLiveEvent(
            timestamp=_timestamp(event),
            event_type="state_changed",
            entity_id=entity_id,
            friendly_name=friendly_name,
            old_state=old_state,
            new_state=new_state,
            domain=domain,
            summary=summary,
        )

    def _parse_call_service(
        self,
        event: dict[str, Any],
        data: dict[str, Any],
    ) -> HomeAssistantLiveEvent:
        domain = _optional_str(data.get("domain"))
        service = _optional_str(data.get("service"))
        service_data = _dict_or_empty(data.get("service_data"))
        entity_id = _optional_str(service_data.get("entity_id"))
        summary = f"Service aufgerufen: {domain}.{service}"
        if entity_id:
            summary = f"{summary} fuer {entity_id}"
        return HomeAssistantLiveEvent(
            timestamp=_timestamp(event),
            event_type="call_service",
            entity_id=entity_id,
            friendly_name=entity_id,
            old_state=None,
            new_state=service,
            domain=domain,
            summary=summary,
        )

    def _parse_automation(
        self,
        event: dict[str, Any],
        data: dict[str, Any],
    ) -> HomeAssistantLiveEvent:
        entity_id = _optional_str(data.get("entity_id"))
        name = _optional_str(data.get("name")) or entity_id or "Automation"
        return HomeAssistantLiveEvent(
            timestamp=_timestamp(event),
            event_type="automation_triggered",
            entity_id=entity_id,
            friendly_name=name,
            old_state=None,
            new_state="triggered",
            domain="automation",
            summary=f"Automation ausgeloest: {name}",
        )

    def _parse_homeassistant_lifecycle(
        self,
        event: dict[str, Any],
        event_type: str,
    ) -> HomeAssistantLiveEvent:
        summary = (
            "Home Assistant wurde gestartet"
            if event_type == "homeassistant_started"
            else "Home Assistant wird gestoppt"
        )
        return HomeAssistantLiveEvent(
            timestamp=_timestamp(event),
            event_type=event_type,
            entity_id=None,
            friendly_name=None,
            old_state=None,
            new_state=None,
            domain="homeassistant",
            summary=summary,
        )

    def _parse_generic(
        self,
        event: dict[str, Any],
        event_type: str,
        data: dict[str, Any],
    ) -> HomeAssistantLiveEvent:
        entity_id = _optional_str(data.get("entity_id"))
        domain = entity_id.split(".", maxsplit=1)[0] if entity_id else None
        return HomeAssistantLiveEvent(
            timestamp=_timestamp(event),
            event_type=event_type,
            entity_id=entity_id,
            friendly_name=entity_id,
            old_state=None,
            new_state=None,
            domain=domain,
            summary=f"Ereignis empfangen: {event_type}",
        )

    def _state_summary(
        self,
        entity_id: str | None,
        friendly_name: str | None,
        old_state: str | None,
        new_state: str | None,
    ) -> str:
        label = friendly_name or entity_id or "Unbekannte Entitaet"
        if old_state == new_state:
            return f"{label}: Attribute aktualisiert"
        return f"{label}: {old_state or 'unknown'} -> {new_state or 'unknown'}"


class HomeAssistantEventStore:
    """Persist the latest Home Assistant live events as JSON."""

    def __init__(self, path: Path, *, limit: int = 100) -> None:
        """Initialize the store."""
        self.path = path
        self.limit = limit
        self._events: deque[HomeAssistantLiveEvent] = deque(maxlen=limit)

    def initialize(self) -> None:
        """Create the store and load existing events."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]\n", encoding="utf-8")
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = []
        self._events.clear()
        for item in payload[-self.limit :]:
            if isinstance(item, dict):
                self._events.append(HomeAssistantLiveEvent(**item))

    def add(self, event: HomeAssistantLiveEvent) -> None:
        """Append and persist an event."""
        self._events.append(event)
        self.save()

    def list_events(self, limit: int | None = None) -> list[HomeAssistantLiveEvent]:
        """Return stored events newest last."""
        events = list(self._events)
        if limit is not None:
            return events[-limit:]
        return events

    def clear(self) -> None:
        """Clear stored events."""
        self._events.clear()
        self.save()

    def count(self) -> int:
        """Return number of currently stored events."""
        return len(self._events)

    def save(self) -> None:
        """Persist events as JSON."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(event) for event in self._events]
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _read_simple_yaml(path: Path) -> dict[str, object]:
    data: dict[str, object] = {}
    current_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", maxsplit=1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" ") and ":" in line:
            key, value = line.split(":", maxsplit=1)
            current_key = key.strip()
            value = value.strip()
            if value.lower() in {"true", "false"}:
                data[current_key] = value.lower() == "true"
            elif value:
                data[current_key] = value
            else:
                data[current_key] = []
            continue
        if current_key and line.strip().startswith("-"):
            value = line.strip().removeprefix("-").strip().strip('"').strip("'")
            items = data.setdefault(current_key, [])
            if isinstance(items, list):
                items.append(value)
    return data


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _timestamp(event: dict[str, Any]) -> str:
    fired = event.get("time_fired")
    if fired:
        return str(fired)
    return datetime.now(UTC).isoformat()
