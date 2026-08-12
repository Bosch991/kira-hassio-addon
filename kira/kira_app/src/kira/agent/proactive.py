"""Policy boundary for future proactive Kira observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProactiveMode(StrEnum):
    """Allowed behavior after Kira detects a relevant situation."""

    DETECT = "detect"
    SUGGEST = "suggest"
    EXECUTE = "execute"


@dataclass(frozen=True, slots=True)
class ProactiveSignal:
    """A detected condition without an implied side effect."""

    key: str
    summary: str
    suggested_intent: str | None = None
    entity_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProactiveDecision:
    """Policy result kept separate from actual planning and execution."""

    signal: ProactiveSignal
    notify: bool
    execute: bool
    reason: str


@dataclass(slots=True)
class ProactivePolicy:
    """Keep detection, suggestion, and execution explicitly separated."""

    mode: ProactiveMode = ProactiveMode.DETECT
    auto_execution_enabled: bool = False
    allowed_auto_intents: set[str] = field(default_factory=set)

    def decide(self, signal: ProactiveSignal) -> ProactiveDecision:
        """Return policy flags without executing anything."""
        if self.mode is ProactiveMode.DETECT:
            return ProactiveDecision(signal, False, False, "detection_only")
        if self.mode is ProactiveMode.SUGGEST:
            return ProactiveDecision(signal, True, False, "suggestion_only")
        allowed = (
            self.auto_execution_enabled
            and signal.suggested_intent is not None
            and signal.suggested_intent in self.allowed_auto_intents
        )
        if allowed:
            return ProactiveDecision(signal, True, True, "explicitly_allowed")
        return ProactiveDecision(signal, True, False, "auto_execution_disabled")
