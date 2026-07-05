"""Future Codex task orchestration boundary."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CodexTaskManager:
    """Placeholder manager for future Codex task coordination."""

    pending_tasks: list[str] = field(default_factory=list)

    def add_task(self, description: str) -> None:
        """Register a future Codex task description."""
        self.pending_tasks.append(description)
