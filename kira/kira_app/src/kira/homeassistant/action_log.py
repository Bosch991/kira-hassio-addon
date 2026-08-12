"""Persistent Home Assistant action log."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class HomeAssistantActionRecord:
    """One logged Home Assistant action decision."""

    id: str
    timestamp: str
    user_text: str
    intent: str
    entities: list[str]
    service_call: dict[str, Any]
    risk_level: str
    auto_executed: bool
    result: str
    error: str | None = None
    previous_states: dict[str, str] = field(default_factory=dict)
    new_states: dict[str, str] = field(default_factory=dict)


class HomeAssistantActionLog:
    """JSON-backed action log."""

    def __init__(self, path: Path) -> None:
        """Initialize the log path."""
        self.path = path
        self._lock = RLock()
        self.logger = logging.getLogger(__name__)

    def initialize(self) -> None:
        """Create the log file when needed."""
        with self._lock:
            self._initialize_unlocked()

    def append(
        self,
        *,
        user_text: str,
        intent: str,
        entities: list[str],
        service_call: dict[str, Any],
        risk_level: str,
        auto_executed: bool,
        result: str,
        error: str | None = None,
        previous_states: dict[str, str] | None = None,
        new_states: dict[str, str] | None = None,
    ) -> HomeAssistantActionRecord:
        """Append one action record."""
        with self._lock:
            self._initialize_unlocked()
            record = HomeAssistantActionRecord(
                id=str(uuid4()),
                timestamp=datetime.now(UTC).isoformat(),
                user_text=user_text,
                intent=intent,
                entities=entities,
                service_call=service_call,
                risk_level=risk_level,
                auto_executed=auto_executed,
                result=result,
                error=error,
                previous_states=previous_states or {},
                new_states=new_states or {},
            )
            records = self._read_unlocked()
            records.append(_record_to_dict(record))
            self._write_unlocked(records[-200:])
            return record

    def last_undoable(self) -> HomeAssistantActionRecord | None:
        """Return the last simple executed action with previous state data."""
        with self._lock:
            self._initialize_unlocked()
            for item in reversed(self._read_unlocked()):
                record = _record_from_dict(item)
                if not record.auto_executed:
                    continue
                if record.result not in {"success", "verified"}:
                    return None
                if not record.previous_states:
                    return None
                if record.service_call.get("domain") not in {
                    "light",
                    "switch",
                    "fan",
                }:
                    return None
                return record if _is_simple_state_change(record.service_call) else None
        return None

    def _read(self) -> list[dict[str, Any]]:
        with self._lock:
            self._initialize_unlocked()
            return self._read_unlocked()

    def _initialize_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_unlocked([])

    def _read_unlocked(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning(
                "Home Assistant action log could not be loaded: %s", exc
            )
            backup = self.path.with_name(
                f"{self.path.name}.corrupt-"
                f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
            )
            try:
                self.path.replace(backup)
                self._write_unlocked([])
            except OSError as backup_error:
                self.logger.error(
                    "Action log recovery could not preserve the bad file: %s",
                    backup_error,
                )
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def _write_unlocked(self, records: list[dict[str, Any]]) -> None:
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _record_to_dict(record: HomeAssistantActionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "timestamp": record.timestamp,
        "user_text": record.user_text,
        "intent": record.intent,
        "entities": record.entities,
        "service_call": record.service_call,
        "risk_level": record.risk_level,
        "auto_executed": record.auto_executed,
        "result": record.result,
        "error": record.error,
        "previous_states": record.previous_states,
        "new_states": record.new_states,
    }


def _record_from_dict(item: dict[str, Any]) -> HomeAssistantActionRecord:
    previous_states = item.get("previous_states", {})
    if not isinstance(previous_states, dict):
        previous_states = {}
    new_states = item.get("new_states", {})
    if not isinstance(new_states, dict):
        new_states = {}
    return HomeAssistantActionRecord(
        id=str(item.get("id", "")),
        timestamp=str(item.get("timestamp", "")),
        user_text=str(item.get("user_text", "")),
        intent=str(item.get("intent", "")),
        entities=[str(entity) for entity in item.get("entities", [])],
        service_call=dict(item.get("service_call", {})),
        risk_level=str(item.get("risk_level", "")),
        auto_executed=bool(item.get("auto_executed", False)),
        result=str(item.get("result", "")),
        error=item.get("error") if isinstance(item.get("error"), str) else None,
        previous_states={
            str(key): str(value) for key, value in previous_states.items()
        },
        new_states={str(key): str(value) for key, value in new_states.items()},
    )


def _is_simple_state_change(service_call: dict[str, Any]) -> bool:
    if service_call.get("service") not in {"toggle", "turn_off", "turn_on"}:
        return False
    data = service_call.get("data", {})
    if not isinstance(data, dict):
        return False
    return not (set(data) - {"entity_id"})
