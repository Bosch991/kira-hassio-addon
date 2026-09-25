"""User-scoped task inspection and cancellation shared by all chat surfaces."""

from __future__ import annotations

import re

from kira.agent.models import AgentRequestContext
from kira.agent.normalization import normalize_text
from kira.agent.task_models import AgentTask, TaskStatus
from kira.agent.task_store import OPEN_TASK_STATUSES, TaskManager

STATUS_LABELS = {
    TaskStatus.ACTIVE: "wartet auf Ausloeser",
    TaskStatus.PENDING_CONFIRMATION: "wartet auf Bestaetigung",
    TaskStatus.RUNNING: "wird ausgefuehrt",
    TaskStatus.COMPLETED: "erledigt",
    TaskStatus.CANCELLED: "abgebrochen",
    TaskStatus.FAILED: "fehlgeschlagen",
    TaskStatus.BLOCKED: "blockiert",
    TaskStatus.EXPIRED: "abgelaufen",
    TaskStatus.DELEGATED: "vorhandene HA-Automation",
}

RESULT_LABELS = {
    "explicitly_confirmed": "Von dir bestaetigt; wartet auf den Ausloeser.",
    "triggered": "Ausloeser erkannt; die Aktion wird ausgefuehrt.",
    "cancelled_by_user": "Von dir abgebrochen; wird nicht mehr ausgefuehrt.",
    "executed_and_verified": "Aktion ausgefuehrt und Ergebnis geprueft.",
    "notification_emitted": "Hinweis an Kiras internen Ereignisbus uebergeben.",
    "notification_failed": "Der Benachrichtigungskanal hat einen Fehler gemeldet.",
    "notification_unavailable": "Kein Benachrichtigungskanal eingerichtet.",
    "confirmation_expired": "Die Frist fuer die Bestaetigung ist abgelaufen.",
    "expiry_reached": "Die Aufgabe ist abgelaufen.",
    "runtime_safety_blocked": (
        "Die erneute Sicherheitspruefung hat die Aktion blockiert."
    ),
    "runtime_plan_changed": (
        "Der Plan hat sich geaendert. Bitte Auftrag neu formulieren."
    ),
    "runtime_confirmation_required": (
        "Neue Bestaetigung noetig. Bitte Auftrag neu formulieren."
    ),
    "execution_failed": "Die Ausfuehrung konnte nicht sicher bestaetigt werden.",
    "execution_interrupted": (
        "Ausfuehrung unterbrochen; keine automatische Wiederholung."
    ),
    "interrupted_during_execution": (
        "Beim Neustart als unterbrochen erkannt; nicht wiederholt."
    ),
    "missing_action_intent": "Die gespeicherte Aktion ist unvollstaendig.",
}

_HELP = (
    "Aufgaben: /tasks [list|all] [Seite], /tasks show <ID>, /tasks cancel <ID>. "
    "Die ersten 8 Zeichen der ID reichen, wenn sie eindeutig sind."
)


class TaskCommandHandler:
    """Manage local tasks without a language model or Home Assistant connection."""

    def __init__(self, manager: TaskManager) -> None:
        """Use the same task store as the live-event runner."""
        self.manager = manager

    def handle(
        self, message: str, request: AgentRequestContext, *, conversation_id: str
    ) -> str | None:
        """Return task output, or decline messages outside this command surface."""
        command = _parse_command(message)
        if command is None:
            return None
        operation, argument = command
        if operation == "help":
            return _HELP
        tasks = [
            task
            for task in self.manager.list()
            if task.user == request.user
            and task.source == request.source
            and (request.user is not None or task.conversation_id == conversation_id)
        ]
        if operation in {"list", "all"}:
            return self._list(tasks, operation, argument)
        if not re.fullmatch(r"[a-f0-9-]{8,36}", argument):
            return _HELP
        matches = [task for task in tasks if task.id.startswith(argument)]
        if not matches:
            return "Keine passende Aufgabe in deinem Anfragekontext gefunden."
        if len(matches) > 1:
            return "Diese ID ist nicht eindeutig. Bitte nutze die vollstaendige ID."
        task = matches[0]
        if operation == "show":
            return self._detail(task)
        cancelled = self.manager.cancel(task.id)
        if cancelled is not None:
            return f"Aufgabe {task.id[:8]} ist abgebrochen und wird nicht ausgefuehrt."
        current = self.manager.get(task.id) or task
        if current.status is TaskStatus.RUNNING:
            return (
                "Die Aufgabe wird bereits ausgefuehrt. Ein Abbruch kann die laufende "
                "Geraeteaktion nicht mehr sicher verhindern. Pruefe den Status erneut."
            )
        if current.status is TaskStatus.DELEGATED:
            return (
                "Dieser Ablauf liegt bei Home Assistant. Ein lokaler Abbruch wuerde "
                "die HA-Automation nicht deaktivieren. Bitte verwalte sie dort: "
                f"{current.delegated_automation_id}."
            )
        return f"Aufgabe {task.id[:8]} ist bereits {STATUS_LABELS[current.status]}."

    def _list(self, tasks: list[AgentTask], operation: str, argument: str) -> str:
        if not re.fullmatch(r"[1-9][0-9]{0,3}", argument or "1"):
            return _HELP
        selected = (
            tasks
            if operation == "all"
            else [task for task in tasks if task.status in OPEN_TASK_STATUSES]
        )
        if not selected:
            return (
                "Du hast keine gespeicherten Aufgaben."
                if operation == "all"
                else "Du hast keine offenen Aufgaben. Verlauf: /tasks all."
            )
        page = int(argument or "1")
        pages = (len(selected) + 19) // 20
        if page > pages:
            return f"Es gibt {pages} Seite(n). Nutze /tasks {operation} 1."
        lines = [f"Deine Aufgaben: {len(selected)} (Seite {page}/{pages})"]
        for task in selected[(page - 1) * 20 : page * 20]:
            description = " ".join(task.request_text.split())
            if len(description) > 160:
                description = description[:157] + "..."
            lines.append(
                f"{task.id[:8]} | {STATUS_LABELS[task.status]} | {description}"
            )
        lines.append("Details: /tasks show <ID>. Abbrechen: /tasks cancel <ID>.")
        if page < pages:
            lines.append(f"Weitere Aufgaben: /tasks {operation} {page + 1}.")
        return "\n".join(lines)

    def _detail(self, task: AgentTask) -> str:
        lines = [
            f"Aufgabe {task.id}",
            f"Status: {STATUS_LABELS[task.status]}",
            f"Auftrag: {task.request_text}",
            f"Ausloeser: {task.trigger.description}",
            f"Ausloeser-Entities: {', '.join(task.trigger.entity_ids)}",
            f"Erstellt: {task.created_at.isoformat(timespec='seconds')}",
            f"Aktualisiert: {task.updated_at.isoformat(timespec='seconds')}",
        ]
        if task.conditions:
            lines.append(
                "Bedingungen: " + "; ".join(c.description for c in task.conditions)
            )
        if (
            task.confirmation_expires_at
            and task.status is TaskStatus.PENDING_CONFIRMATION
        ):
            lines.append(
                f"Bestaetigung bis: {task.confirmation_expires_at.isoformat()}"
            )
        if task.delegated_automation_id:
            lines.append(f"HA-Automation: {task.delegated_automation_id}")
        if task.last_result:
            result = RESULT_LABELS.get(task.last_result, task.last_result)
            if task.last_result.startswith("planning_failed:"):
                result = "Planung fehlgeschlagen: " + task.last_result.split(":", 1)[1]
            lines.append(f"Ergebnis: {result}")
        return "\n".join(lines)


def _parse_command(message: str) -> tuple[str, str] | None:
    parts = message.strip().split()
    if parts and parts[0].lower() == "/tasks":
        arguments = [part.lower() for part in parts[1:]]
        if not arguments:
            return "list", ""
        if len(arguments) <= 2 and arguments[0] in {"list", "all", "show", "cancel"}:
            return arguments[0], arguments[1] if len(arguments) == 2 else ""
        return "help", ""
    text = normalize_text(message).strip(" .!?")
    if text in {
        "welche aufgaben sind noch offen",
        "welche aufgaben sind offen",
        "welche aufgaben sind aktiv",
        "zeige meine offenen aufgaben",
        "zeig meine offenen aufgaben",
    }:
        return "list", ""
    if text in {
        "zeige meine aufgaben",
        "zeig meine aufgaben",
        "welche aufgaben habe ich",
    }:
        return "all", ""
    match = re.fullmatch(
        r"(?:brich|breche) (?:die )?aufgabe ([a-f0-9-]{8,36}) ab", text
    )
    if match:
        return "cancel", match[1]
    match = re.fullmatch(
        r"(?:zeige|zeig|was ist mit) (?:der )?aufgabe ([a-f0-9-]{8,36})", text
    )
    if match:
        return "show", match[1]
    return None
