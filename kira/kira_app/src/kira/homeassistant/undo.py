"""Undo planning for simple Home Assistant actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kira.homeassistant.action_log import HomeAssistantActionLog
from kira.homeassistant.client import HomeAssistantResult
from kira.homeassistant.services import HomeAssistantServices


@dataclass(frozen=True, slots=True)
class UndoResult:
    """Result of an undo attempt."""

    ok: bool
    message: str


class HomeAssistantUndoPlanner:
    """Prepare and run simple undo operations."""

    def __init__(
        self,
        *,
        action_log: HomeAssistantActionLog,
        services: HomeAssistantServices,
    ) -> None:
        """Initialize the planner."""
        self.action_log = action_log
        self.services = services

    def undo_last(self) -> UndoResult:
        """Undo the last simple action when safe enough."""
        record = self.action_log.last_undoable()
        if record is None:
            return UndoResult(
                ok=False,
                message=(
                    "Ich finde keine einfache Aktion, die ich sicher "
                    "rueckgaengig machen kann."
                ),
            )
        domain = str(record.service_call.get("domain", ""))
        if domain not in {"light", "switch", "fan"}:
            return UndoResult(
                ok=False,
                message="Diese Aktion kann ich nicht sicher rueckgaengig machen.",
            )
        on_entities = [
            entity_id
            for entity_id, state in record.previous_states.items()
            if state == "on"
        ]
        off_entities = [
            entity_id
            for entity_id, state in record.previous_states.items()
            if state == "off"
        ]
        results: list[HomeAssistantResult] = []
        if on_entities:
            results.append(self.services.call(domain, "turn_on", _payload(on_entities)))
        if off_entities:
            results.append(
                self.services.call(domain, "turn_off", _payload(off_entities))
            )
        if not results:
            return UndoResult(
                ok=False,
                message="Der vorherige Zustand ist nicht sicher wiederherstellbar.",
            )
        if all(result.ok for result in results):
            return UndoResult(
                ok=True,
                message="Letzte Aktion wurde rueckgaengig gemacht.",
            )
        return UndoResult(ok=False, message="Undo ist fehlgeschlagen.")


def _payload(entity_ids: list[str]) -> dict[str, Any]:
    return {"entity_id": entity_ids if len(entity_ids) > 1 else entity_ids[0]}
