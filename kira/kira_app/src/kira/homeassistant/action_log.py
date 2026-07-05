"""Persistent Home Assistant action log."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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

    def initialize(self) -> None:
        """Create the log file when needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]\n", encoding="utf-8")

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
        self.initialize()
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
        records = self._read()
        records.append(_record_to_dict(record))
        self.path.write_text(
            json.dumps(records[-200:], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return record

    def last_undoable(self) -> HomeAssistantActionRecord | None:
        """Return the last simple executed action with previous state data."""
        for item in reversed(self._read()):
            record = _record_from_dict(item)
            if (
                record.auto_executed
                and record.result == "success"
                and record.previous_states
                and record.service_call.get("domain") in {"light", "switch", "fan"}
            ):
                return record
        return None

    def _read(self) -> list[dict[str, Any]]:
        self.initialize()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]


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
