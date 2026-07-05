"""Local-only telemetry collection."""

from __future__ import annotations

import json
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class TelemetrySnapshot:
    """Local telemetry snapshot."""

    uptime_seconds: float
    plugin_load_times: dict[str, float] = field(default_factory=dict)
    memory_mb: float = 0.0
    response_times: dict[str, list[float]] = field(default_factory=dict)


class TelemetryStore:
    """Collect and persist local telemetry without network transmission."""

    def __init__(self, path: Path) -> None:
        """Initialize telemetry storage."""
        self.path = path
        self.started_at = time.perf_counter()
        self.plugin_load_times: dict[str, float] = {}
        self.response_times: dict[str, list[float]] = {}
        if not tracemalloc.is_tracing():
            tracemalloc.start()

    def record_plugin_load(self, name: str, seconds: float) -> None:
        """Record how long one plugin took to load."""
        self.plugin_load_times[name] = seconds
        self.save()

    def record_response_time(self, name: str, seconds: float) -> None:
        """Record a response time measurement."""
        self.response_times.setdefault(name, []).append(seconds)
        self.save()

    def snapshot(self) -> TelemetrySnapshot:
        """Return the current telemetry snapshot."""
        return TelemetrySnapshot(
            uptime_seconds=time.perf_counter() - self.started_at,
            plugin_load_times=dict(self.plugin_load_times),
            memory_mb=self._memory_mb(),
            response_times={
                key: list(value) for key, value in self.response_times.items()
            },
        )

    def save(self) -> None:
        """Persist telemetry to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(self.snapshot()), indent=2),
            encoding="utf-8",
        )

    def _memory_mb(self) -> float:
        current, _ = tracemalloc.get_traced_memory()
        return float(current / 1024 / 1024)
