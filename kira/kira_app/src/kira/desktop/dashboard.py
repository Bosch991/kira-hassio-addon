"""Dashboard and quick-action logic for the Kira desktop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from kira.chat.session import ChatSession
from kira.version import KIRA_VERSION


@dataclass(frozen=True, slots=True)
class StatusCard:
    """One compact status card shown on the desktop dashboard."""

    title: str
    status: str
    detail: str = ""
    level: str = "ok"


@dataclass(frozen=True, slots=True)
class HealthLine:
    """One component health line."""

    name: str
    status: str
    detail: str = ""
    level: str = "ok"


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    """Display-ready desktop dashboard data."""

    version: str
    cards: list[StatusCard]
    health: list[HealthLine]
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class DesktopCommandResult:
    """Result of a desktop quick action."""

    user_text: str
    response: str


class DesktopDashboardController:
    """Build dashboard state and execute desktop quick actions."""

    QUICK_COMMANDS: dict[str, str] = {
        "home_status": "/ha status",
        "briefing": "/briefing",
        "briefing_speak": "/briefing speak",
        "updates_check": "/updates check",
        "updates_status": "/updates status",
    }

    def __init__(self, app: Any, session: ChatSession | None = None) -> None:
        """Initialize the controller for a running Kira application."""
        self.app = app
        self.session = session or ChatSession.from_app(app)

    def snapshot(self) -> DashboardSnapshot:
        """Return current dashboard data without expensive remote fetches."""
        health = self.health_lines()
        health_by_name = {item.name: item for item in health}
        update_status = self._local_update_status()
        cards = [
            StatusCard("Kira", "laeuft", f"Version {KIRA_VERSION}", "ok"),
            StatusCard("Server", "bereit", "Desktop lokal gestartet", "ok"),
            self._plugin_card("Home Assistant", health_by_name.get("homeassistant")),
            self._plugin_card("OpenAI", health_by_name.get("openai")),
            self._plugin_card("Voice", health_by_name.get("voice")),
            self._memory_knowledge_card(health_by_name),
            update_status,
        ]
        return DashboardSnapshot(
            version=KIRA_VERSION,
            cards=cards,
            health=health,
            checked_at=datetime.now(UTC),
        )

    def health_lines(self) -> list[HealthLine]:
        """Return friendly health data for desktop display."""
        plugin_manager = getattr(self.app, "plugin_manager", None)
        if plugin_manager is None:
            return []
        try:
            results = plugin_manager.health()
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            return [
                HealthLine(
                    "health",
                    "nicht verfuegbar",
                    self.friendly_error(exc),
                    "warning",
                )
            ]

        lines: list[HealthLine] = []
        for name in sorted(results):
            result = results[name]
            message = str(getattr(result, "message", "ok"))
            level = self._health_level(
                name, bool(getattr(result, "ok", False)), message
            )
            lines.append(
                HealthLine(
                    name=name,
                    status="ok" if getattr(result, "ok", False) else "fehler",
                    detail=message,
                    level=level,
                )
            )
        return lines

    def run_action(self, action: str) -> DesktopCommandResult:
        """Execute a desktop quick action and return display text."""
        if action in self.QUICK_COMMANDS:
            command = self.QUICK_COMMANDS[action]
            return self.run_chat_command(command)
        if action == "healthcheck":
            return DesktopCommandResult("Healthcheck", self.format_healthcheck())
        if action == "version":
            return DesktopCommandResult("Version", f"Kira Version: {KIRA_VERSION}")
        if action == "server_start":
            return DesktopCommandResult(
                "Server starten",
                "Serverstart im Desktop ist vorbereitet. Starte sicher mit:\n"
                "python -m kira server",
            )
        if action == "server_stop":
            return DesktopCommandResult(
                "Server stoppen",
                "Beende den Server im Terminal mit STRG+C. Kira beendet keine "
                "fremden Prozesse automatisch.",
            )
        if action == "server_status":
            return DesktopCommandResult(
                "Serverstatus",
                "Der Desktop laeuft lokal. Den API-Server pruefst du ueber "
                "GET /health oder mit python -m kira server.",
            )
        if action == "restart_hint":
            update_service = getattr(self.app, "update_service", None)
            hint = (
                update_service.restart_hint()
                if update_service is not None
                else "Beende Kira mit STRG+C und starte sie danach erneut."
            )
            return DesktopCommandResult("Neustart-Hinweis", hint)
        return DesktopCommandResult(action, "Unbekannte Desktop-Aktion.")

    def run_chat_command(self, command: str) -> DesktopCommandResult:
        """Execute one local chat command through the existing chat session."""
        try:
            if hasattr(self.session, "handle_local_input"):
                response = self.session.handle_local_input(command)
            else:
                response = self.session.handle_assist_message(command)
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            response = self.friendly_error(exc)
        return DesktopCommandResult(command, response)

    def format_healthcheck(self) -> str:
        """Return a readable healthcheck summary."""
        lines = ["Healthcheck:"]
        for item in self.health_lines():
            detail = f" - {item.detail}" if item.detail else ""
            lines.append(f"{item.name}: {item.status}{detail}")
        if len(lines) == 1:
            lines.append("Keine Healthcheck-Daten verfuegbar.")
        return "\n".join(lines)

    def friendly_error(self, exc: Exception) -> str:
        """Translate technical exceptions into user-facing desktop messages."""
        name = exc.__class__.__name__.lower()
        text = str(exc).lower()
        if "home" in text or "connection" in name or "timeout" in name:
            return (
                "Home Assistant ist gerade nicht erreichbar. Pruefe, ob Home "
                "Assistant laeuft und die URL stimmt."
            )
        if "openai" in text or "authentication" in name or "api" in name:
            return (
                "OpenAI konnte nicht erreicht werden oder der API-Key ist "
                "ungueltig. Secrets werden nicht angezeigt."
            )
        if "voice" in text or "eleven" in text or "audio" in text:
            return "Voice ist gerade nicht verfuegbar. Kira laeuft ohne Absturz weiter."
        return (
            "Die Desktop-Aktion konnte nicht ausgefuehrt werden. Details stehen im Log."
        )

    def _local_update_status(self) -> StatusCard:
        update_service = getattr(self.app, "update_service", None)
        if update_service is None:
            return StatusCard("Updates", "nicht verfuegbar", "", "warning")
        try:
            status = update_service.local_status()
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            return StatusCard(
                "Updates", "nicht verfuegbar", self.friendly_error(exc), "warning"
            )
        if not status.clean:
            return StatusCard("Updates", "lokale Aenderungen", status.commit, "warning")
        return StatusCard("Updates", "nicht geprueft", status.commit, "warning")

    def _plugin_card(self, title: str, health: HealthLine | None) -> StatusCard:
        if health is None:
            return StatusCard(title, "nicht verfuegbar", "", "warning")
        return StatusCard(title, health.status, health.detail, health.level)

    def _memory_knowledge_card(self, health: dict[str, HealthLine]) -> StatusCard:
        memory = health.get("memory")
        knowledge = health.get("knowledge")
        if memory is None and knowledge is None:
            return StatusCard("Memory/Knowledge", "nicht verfuegbar", "", "warning")
        parts = []
        level = "ok"
        for item in (memory, knowledge):
            if item is None:
                continue
            parts.append(f"{item.name}: {item.detail or item.status}")
            if item.level != "ok":
                level = item.level
        return StatusCard("Memory/Knowledge", "ok", "; ".join(parts), level)

    def _health_level(self, name: str, ok: bool, message: str) -> str:
        normalized = message.lower()
        if name == "openart" and "missing configuration" in normalized:
            return "warning"
        if not ok:
            return "error"
        if "not configured" in normalized or "fallback" in normalized:
            return "warning"
        return "ok"
