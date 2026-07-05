"""Lightweight scheduler registry without automation execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    """Definition for a future scheduled task."""

    name: str
    schedule: str
    enabled: bool = True
    next_run: datetime | None = None


class Scheduler:
    """Registry for future time-based tasks."""

    def __init__(self) -> None:
        """Initialize an empty scheduler registry."""
        self._tasks: dict[str, ScheduledTask] = {}

    def register(self, task: ScheduledTask) -> None:
        """Register or replace a scheduled task."""
        self._tasks[task.name] = task

    def unregister(self, name: str) -> None:
        """Remove a scheduled task."""
        self._tasks.pop(name, None)

    def list_tasks(self) -> list[ScheduledTask]:
        """List registered scheduled tasks."""
        return list(self._tasks.values())
