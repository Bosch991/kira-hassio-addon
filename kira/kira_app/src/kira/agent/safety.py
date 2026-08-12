"""Plan-wide validation and safety decisions for Home Assistant actions."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from kira.agent.entities import EntityCatalog
from kira.agent.models import ActionPlan, PlanStep
from kira.homeassistant.permissions import (
    HomeAssistantPermissionEngine,
    PermissionDecision,
    RiskLevel,
)
from kira.homeassistant.services import HomeAssistantServices

_ALLOWED_STEP_DATA: dict[tuple[str, str], frozenset[str]] = {
    ("light", "turn_on"): frozenset(
        {"brightness_pct", "brightness_step_pct", "color_temp_kelvin"}
    ),
    ("climate", "set_temperature"): frozenset({"temperature"}),
}


@dataclass(frozen=True, slots=True)
class ServiceRegistryResult:
    """Home Assistant service registry snapshot."""

    services: frozenset[tuple[str, str]]
    error: str | None = None


class HomeAssistantServiceRegistry:
    """Read and normalize the Home Assistant service catalog."""

    def __init__(self, services: HomeAssistantServices) -> None:
        """Initialize the service boundary."""
        self.services = services

    def load(self) -> ServiceRegistryResult:
        """Return available domain/service pairs from Home Assistant."""
        result = self.services.list_services()
        if not result.ok or not isinstance(result.data, list):
            return ServiceRegistryResult(
                services=frozenset(),
                error=result.error or "Servicekatalog ist nicht verfuegbar.",
            )
        pairs: set[tuple[str, str]] = set()
        for domain_item in result.data:
            if not isinstance(domain_item, dict):
                continue
            domain = domain_item.get("domain")
            definitions = domain_item.get("services")
            if not isinstance(domain, str) or not isinstance(definitions, dict):
                continue
            pairs.update((domain, str(service)) for service in definitions)
        return ServiceRegistryResult(services=frozenset(pairs))


@dataclass(frozen=True, slots=True)
class PlanSafetyReview:
    """Aggregated safety decision for a complete action plan."""

    decision: PermissionDecision
    risk_level: RiskLevel
    reasons: tuple[str, ...]

    @property
    def auto_execute(self) -> bool:
        """Return whether every plan step may run without confirmation."""
        return self.decision is PermissionDecision.AUTO_EXECUTE


class PlanSafetyManager:
    """Validate entities, services, capabilities, and permissions plan-wide."""

    def __init__(
        self,
        *,
        permissions: HomeAssistantPermissionEngine,
        service_registry: HomeAssistantServiceRegistry,
    ) -> None:
        """Initialize safety dependencies."""
        self.permissions = permissions
        self.service_registry = service_registry
        self.logger = logging.getLogger(__name__)

    def review(self, plan: ActionPlan, catalog: EntityCatalog) -> PlanSafetyReview:
        """Review the full plan before any service call is made."""
        if not plan.steps:
            return self._review(
                PermissionDecision.BLOCK, RiskLevel.MEDIUM, "empty_plan"
            )
        registry = self.service_registry.load()
        if registry.error:
            return self._review(
                PermissionDecision.BLOCK,
                RiskLevel.MEDIUM,
                "service_registry_unavailable",
            )

        decisions: list[PermissionDecision] = []
        risks: list[RiskLevel] = []
        reasons: list[str] = []
        all_rooms: set[str] = set()
        all_entity_ids: list[str] = []
        for step in plan.steps:
            validation_error = self._validate_step(step, catalog, registry)
            if validation_error:
                return self._review(
                    PermissionDecision.BLOCK,
                    RiskLevel.HIGH,
                    validation_error,
                )
            rooms = {
                entity.room
                for entity_id in step.entity_ids
                if (entity := catalog.by_id.get(entity_id)) is not None and entity.room
            }
            all_rooms.update(str(room) for room in rooms)
            all_entity_ids.extend(step.entity_ids)
            permission = self.permissions.evaluate(
                domain=step.domain,
                service=step.service,
                entity_ids=step.entity_ids,
                area_ids=sorted(str(room) for room in rooms),
            )
            decisions.append(permission.decision)
            risks.append(permission.risk_level)
            reasons.append(permission.reason)

        config = self.permissions.config
        if config.require_confirm_for_multiple_rooms and len(all_rooms) > 1:
            decisions.append(PermissionDecision.REQUIRE_CONFIRM)
            reasons.append("multiple_rooms_in_plan")
        if len(set(all_entity_ids)) > config.require_confirm_over_entity_count:
            decisions.append(PermissionDecision.REQUIRE_CONFIRM)
            reasons.append("too_many_entities_in_plan")

        decision = _strictest_decision(decisions)
        risk = _highest_risk(risks)
        if plan.confidence < 0.55:
            decision = PermissionDecision.BLOCK
            reasons.append("plan_confidence_too_low")
        elif plan.confidence < 0.8 and risk is not RiskLevel.LOW:
            decisions.append(PermissionDecision.REQUIRE_CONFIRM)
            reasons.append("low_confidence_risky_plan")
            decision = _strictest_decision(decisions)
        review = PlanSafetyReview(decision, risk, tuple(dict.fromkeys(reasons)))
        self.logger.info(
            "Agent plan safety: plan=%s decision=%s risk=%s reasons=%s",
            plan.id,
            review.decision,
            review.risk_level,
            ",".join(review.reasons),
        )
        return review

    def _validate_step(
        self,
        step: PlanStep,
        catalog: EntityCatalog,
        registry: ServiceRegistryResult,
    ) -> str | None:
        if not step.entity_ids:
            return "step_without_entities"
        if (step.domain, step.service) not in registry.services:
            return f"unknown_service:{step.domain}.{step.service}"
        parameter_error = self._validate_parameters(step, catalog)
        if parameter_error:
            return parameter_error
        for entity_id in step.entity_ids:
            entity = catalog.by_id.get(entity_id)
            if entity is None:
                return f"unknown_entity:{entity_id}"
            if not entity.available:
                return f"unavailable_entity:{entity_id}"
            if entity.domain != step.domain:
                return f"domain_mismatch:{entity_id}"
            if "brightness_pct" in step.data or "brightness_step_pct" in step.data:
                if "brightness" not in entity.capabilities:
                    return f"unsupported_brightness:{entity_id}"
            if "color_temp_kelvin" in step.data:
                if "color_temperature" not in entity.capabilities:
                    return f"unsupported_color_temperature:{entity_id}"
        return None

    def _validate_parameters(
        self,
        step: PlanStep,
        catalog: EntityCatalog,
    ) -> str | None:
        if "entity_id" in step.data:
            return "reserved_parameter:entity_id"
        allowed = _ALLOWED_STEP_DATA.get((step.domain, step.service), frozenset())
        unknown = sorted(set(step.data) - allowed)
        if unknown:
            return f"unsupported_parameter:{unknown[0]}"
        if {"brightness_pct", "brightness_step_pct"} <= set(step.data):
            return "conflicting_brightness_parameters"

        brightness = _finite_number(step.data.get("brightness_pct"))
        if "brightness_pct" in step.data and (
            brightness is None or not 0 <= brightness <= 100
        ):
            return "invalid_parameter:brightness_pct"
        brightness_step = _finite_number(step.data.get("brightness_step_pct"))
        if "brightness_step_pct" in step.data and (
            brightness_step is None
            or brightness_step == 0
            or not -100 <= brightness_step <= 100
        ):
            return "invalid_parameter:brightness_step_pct"

        color_temperature = _finite_number(step.data.get("color_temp_kelvin"))
        if "color_temp_kelvin" in step.data:
            if color_temperature is None:
                return "invalid_parameter:color_temp_kelvin"
            for entity_id in step.entity_ids:
                entity = catalog.by_id.get(entity_id)
                if entity is None:
                    continue
                minimum = _attribute_number(
                    entity.attributes, "min_color_temp_kelvin", default=2000
                )
                maximum = _attribute_number(
                    entity.attributes, "max_color_temp_kelvin", default=6500
                )
                if not minimum <= color_temperature <= maximum:
                    return f"invalid_color_temperature:{entity_id}"

        temperature = _finite_number(step.data.get("temperature"))
        if "temperature" in step.data:
            if temperature is None:
                return "invalid_parameter:temperature"
            for entity_id in step.entity_ids:
                entity = catalog.by_id.get(entity_id)
                if entity is None:
                    continue
                unit = str(entity.attributes.get("temperature_unit", "C")).upper()
                fallback_min, fallback_max = (
                    (0.0, 120.0) if "F" in unit else (-20.0, 50.0)
                )
                minimum = _attribute_number(
                    entity.attributes, "min_temp", default=fallback_min
                )
                maximum = _attribute_number(
                    entity.attributes, "max_temp", default=fallback_max
                )
                if not minimum <= temperature <= maximum:
                    return f"invalid_temperature:{entity_id}"
        return None

    def _review(
        self,
        decision: PermissionDecision,
        risk_level: RiskLevel,
        reason: str,
    ) -> PlanSafetyReview:
        review = PlanSafetyReview(decision, risk_level, (reason,))
        self.logger.info(
            "Agent plan safety: decision=%s risk=%s reason=%s",
            decision,
            risk_level,
            reason,
        )
        return review


def _strictest_decision(decisions: list[PermissionDecision]) -> PermissionDecision:
    if PermissionDecision.BLOCK in decisions:
        return PermissionDecision.BLOCK
    if PermissionDecision.REQUIRE_CONFIRM in decisions:
        return PermissionDecision.REQUIRE_CONFIRM
    return PermissionDecision.AUTO_EXECUTE


def _highest_risk(risks: list[RiskLevel]) -> RiskLevel:
    order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
    return max(risks, key=order.get, default=RiskLevel.MEDIUM)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _attribute_number(
    attributes: dict[str, Any],
    name: str,
    *,
    default: float,
) -> float:
    value = _finite_number(attributes.get(name))
    return default if value is None else value
