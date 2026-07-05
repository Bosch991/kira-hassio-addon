"""Permission decisions for Home Assistant actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class PermissionDecision(StrEnum):
    """Decision returned by the permission engine."""

    AUTO_EXECUTE = "auto_execute"
    REQUIRE_CONFIRM = "require_confirm"
    BLOCK = "block"


class RiskLevel(StrEnum):
    """Risk level for a Home Assistant service call."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class HomeAssistantPermissionConfig:
    """Loaded Home Assistant permission configuration."""

    allowed_domains: set[str] = field(default_factory=set)
    allowed_rooms: set[str] = field(default_factory=set)
    allowed_entities: set[str] = field(default_factory=set)
    blocked_entities: set[str] = field(default_factory=set)
    low_risk_auto_execute: set[str] = field(default_factory=set)
    require_confirm: set[str] = field(default_factory=set)
    always_block: set[str] = field(default_factory=set)
    risk_levels: dict[str, set[str]] = field(default_factory=dict)
    require_confirm_for_multiple_rooms: bool = True
    require_confirm_for_risky_domains: bool = True
    require_confirm_over_entity_count: int = 5

    @classmethod
    def load(cls, path: Path) -> HomeAssistantPermissionConfig:
        """Load permissions from YAML, using empty defaults when missing."""
        if not path.exists():
            return cls.default()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return cls()
        confirm_rules = data.get("confirm_rules", {})
        if not isinstance(confirm_rules, dict):
            confirm_rules = {}
        risk_levels = data.get("risk_levels", {})
        if not isinstance(risk_levels, dict):
            risk_levels = {}
        return cls(
            allowed_domains=_string_set(data.get("allowed_domains")),
            allowed_rooms=_string_set(data.get("allowed_rooms")),
            allowed_entities=_string_set(data.get("allowed_entities")),
            blocked_entities=_string_set(data.get("blocked_entities")),
            low_risk_auto_execute=_string_set(data.get("low_risk_auto_execute")),
            require_confirm=_string_set(data.get("require_confirm")),
            always_block=_string_set(data.get("always_block")),
            risk_levels={
                str(level): _string_set(domains)
                for level, domains in risk_levels.items()
            },
            require_confirm_for_multiple_rooms=bool(
                confirm_rules.get("require_confirm_for_multiple_rooms", True)
            ),
            require_confirm_for_risky_domains=bool(
                confirm_rules.get("require_confirm_for_risky_domains", True)
            ),
            require_confirm_over_entity_count=int(
                confirm_rules.get("require_confirm_over_entity_count", 5)
            ),
        )

    @classmethod
    def default(cls) -> HomeAssistantPermissionConfig:
        """Return safe default permissions."""
        return cls(
            allowed_domains={
                "light",
                "media_player",
                "fan",
                "scene",
                "switch",
                "cover",
                "climate",
                "automation",
                "script",
            },
            allowed_rooms={
                "kueche",
                "esszimmer",
                "wohnzimmer_tv",
                "badezimmer",
                "kinderzimmer",
                "schlafzimmer",
                "arbeit",
            },
            low_risk_auto_execute={
                "light.turn_on",
                "light.turn_off",
                "light.toggle",
                "media_player.volume_set",
                "media_player.volume_up",
                "media_player.volume_down",
                "media_player.media_stop",
                "fan.turn_on",
                "fan.turn_off",
            },
            require_confirm={
                "switch.turn_on",
                "switch.turn_off",
                "cover.open_cover",
                "cover.close_cover",
                "climate.set_temperature",
                "automation.turn_off",
                "script.turn_on",
            },
            always_block={
                "lock.unlock",
                "alarm_control_panel.alarm_disarm",
            },
            risk_levels={
                "low": {"light", "media_player", "fan"},
                "medium": {"switch", "cover", "climate", "automation", "script"},
                "high": {"lock", "alarm_control_panel"},
            },
        )


@dataclass(frozen=True, slots=True)
class HomeAssistantPermissionResult:
    """Permission decision plus explanation."""

    decision: PermissionDecision
    risk_level: RiskLevel
    reason: str
    auto_execute: bool


class HomeAssistantPermissionEngine:
    """Evaluate whether a Home Assistant action may run automatically."""

    def __init__(self, config: HomeAssistantPermissionConfig) -> None:
        """Initialize the permission engine."""
        self.config = config

    def evaluate(
        self,
        *,
        domain: str,
        service: str,
        entity_ids: list[str],
        area_ids: list[str] | None = None,
    ) -> HomeAssistantPermissionResult:
        """Return a permission decision for a service call."""
        action = f"{domain}.{service}"
        risk_level = self.risk_level(domain)
        area_ids = area_ids or []
        if action in self.config.always_block:
            return self._result(PermissionDecision.BLOCK, risk_level, "blocked_action")
        if any(entity_id in self.config.blocked_entities for entity_id in entity_ids):
            return self._result(PermissionDecision.BLOCK, risk_level, "blocked_entity")
        if self.config.allowed_domains and domain not in self.config.allowed_domains:
            return self._result(
                PermissionDecision.BLOCK,
                risk_level,
                "domain_not_allowed",
            )
        if self.config.allowed_entities:
            unknown = [
                entity_id
                for entity_id in entity_ids
                if entity_id not in self.config.allowed_entities
            ]
            if unknown:
                return self._result(
                    PermissionDecision.REQUIRE_CONFIRM,
                    risk_level,
                    "entity_not_explicitly_allowed",
                )
        if action in self.config.require_confirm:
            return self._result(
                PermissionDecision.REQUIRE_CONFIRM,
                risk_level,
                "action_requires_confirm",
            )
        if self.config.require_confirm_for_multiple_rooms and len(set(area_ids)) > 1:
            return self._result(
                PermissionDecision.REQUIRE_CONFIRM,
                risk_level,
                "multiple_rooms",
            )
        if len(entity_ids) > self.config.require_confirm_over_entity_count:
            return self._result(
                PermissionDecision.REQUIRE_CONFIRM,
                risk_level,
                "too_many_entities",
            )
        if (
            risk_level is not RiskLevel.LOW
            and self.config.require_confirm_for_risky_domains
        ):
            return self._result(
                PermissionDecision.REQUIRE_CONFIRM,
                risk_level,
                "risky_domain",
            )
        if action in self.config.low_risk_auto_execute:
            return self._result(
                PermissionDecision.AUTO_EXECUTE,
                risk_level,
                "low_risk_auto_execute",
            )
        return self._result(
            PermissionDecision.REQUIRE_CONFIRM,
            risk_level,
            "not_auto_allowed",
        )

    def risk_level(self, domain: str) -> RiskLevel:
        """Return configured risk level for a domain."""
        for level, domains in self.config.risk_levels.items():
            if domain not in domains:
                continue
            try:
                return RiskLevel(level)
            except ValueError:
                return RiskLevel.MEDIUM
        return RiskLevel.MEDIUM

    def _result(
        self,
        decision: PermissionDecision,
        risk_level: RiskLevel,
        reason: str,
    ) -> HomeAssistantPermissionResult:
        return HomeAssistantPermissionResult(
            decision=decision,
            risk_level=risk_level,
            reason=reason,
            auto_execute=decision is PermissionDecision.AUTO_EXECUTE,
        )


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if item is not None}
