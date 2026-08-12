"""State-aware Home Assistant plan execution and result verification."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from kira.agent.entities import EntityCatalog
from kira.agent.models import ActionPlan, PlanStep
from kira.homeassistant.action_log import HomeAssistantActionLog
from kira.homeassistant.client import HomeAssistantClient
from kira.homeassistant.permissions import HomeAssistantPermissionEngine
from kira.homeassistant.services import HomeAssistantServices


class VerificationStatus(StrEnum):
    """Possible results of reading state after a service call."""

    VERIFIED = "verified"
    ACCEPTED = "accepted"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Observed state after an action."""

    status: VerificationStatus
    states: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str | None = None


class ResultValidator:
    """Read affected entities after an action with a bounded retry."""

    def __init__(
        self,
        client: HomeAssistantClient,
        *,
        attempts: int = 2,
        delay_seconds: float = 0.25,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize verification limits."""
        self.client = client
        self.attempts = max(1, attempts)
        self.delay_seconds = max(0.0, delay_seconds)
        self.sleep_fn = sleep_fn

    def verify(
        self,
        step: PlanStep,
        *,
        previous_attributes: dict[str, dict[str, Any]] | None = None,
    ) -> VerificationResult:
        """Verify expected states using fresh Home Assistant reads."""
        last_states: dict[str, str] = {}
        last_attributes: dict[str, dict[str, Any]] = {}
        last_error: str | None = None
        for attempt in range(self.attempts):
            observation = self.observe(step.entity_ids)
            if observation.status is VerificationStatus.UNAVAILABLE:
                last_error = observation.error
            else:
                last_states = observation.states
                last_attributes = observation.attributes
                attribute_match = _attribute_expectations_match(
                    step,
                    observation.attributes,
                    previous_attributes=previous_attributes,
                )
                if not step.expected_states and attribute_match is None:
                    return VerificationResult(
                        VerificationStatus.ACCEPTED,
                        observation.states,
                        observation.attributes,
                    )
                if (
                    self._matches(step, observation.states)
                    and attribute_match is not False
                ):
                    return VerificationResult(
                        VerificationStatus.VERIFIED,
                        observation.states,
                        observation.attributes,
                    )
            if attempt + 1 < self.attempts and self.delay_seconds:
                self.sleep_fn(self.delay_seconds)
        if last_states:
            return VerificationResult(
                VerificationStatus.MISMATCH,
                last_states,
                last_attributes,
                "Der erwartete Zustand wurde nicht erreicht.",
            )
        return VerificationResult(
            VerificationStatus.UNAVAILABLE,
            last_states,
            last_attributes,
            last_error or "Ergebnis konnte nicht verifiziert werden.",
        )

    def observe(self, entity_ids: list[str]) -> VerificationResult:
        """Read current states once immediately before an action step."""
        states: dict[str, str] = {}
        attributes: dict[str, dict[str, Any]] = {}
        for entity_id in entity_ids:
            result = self.client.entity(entity_id)
            if not result.ok or not isinstance(result.data, dict):
                return VerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    states,
                    attributes,
                    result.error or f"State fuer {entity_id} nicht lesbar.",
                )
            state = str(result.data.get("state", "unknown"))
            states[entity_id] = state
            raw_attributes = result.data.get("attributes", {})
            attributes[entity_id] = (
                dict(raw_attributes) if isinstance(raw_attributes, dict) else {}
            )
            if state in {"unavailable", "unknown"}:
                return VerificationResult(
                    VerificationStatus.UNAVAILABLE,
                    states,
                    attributes,
                    f"{entity_id} ist {state}.",
                )
        return VerificationResult(VerificationStatus.VERIFIED, states, attributes)

    def _matches(self, step: PlanStep, states: dict[str, str]) -> bool:
        if not step.expected_states:
            return bool(states) and all(
                state not in {"unavailable", "unknown"} for state in states.values()
            )
        return all(
            states.get(entity_id) == expected
            for entity_id, expected in step.expected_states.items()
        )


class StepExecutionStatus(StrEnum):
    """Outcome for one plan step."""

    SKIPPED = "skipped"
    VERIFIED = "verified"
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class StepExecutionResult:
    """Execution details for one action step."""

    step: PlanStep
    status: StepExecutionStatus
    previous_states: dict[str, str]
    observed_states: dict[str, str]
    previous_attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    observed_attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    service_called: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PlanExecutionResult:
    """Ordered outcomes for a complete plan."""

    plan: ActionPlan
    steps: tuple[StepExecutionResult, ...]

    @property
    def ok(self) -> bool:
        """Return whether no step definitively failed."""
        return all(
            result.status
            in {
                StepExecutionStatus.SKIPPED,
                StepExecutionStatus.VERIFIED,
                StepExecutionStatus.ACCEPTED,
            }
            for result in self.steps
        )


class ActionExecutor:
    """Execute pre-reviewed plans and never assume successful state changes."""

    def __init__(
        self,
        *,
        services: HomeAssistantServices,
        validator: ResultValidator,
        permissions: HomeAssistantPermissionEngine,
        action_log: HomeAssistantActionLog,
    ) -> None:
        """Initialize execution dependencies."""
        self.services = services
        self.validator = validator
        self.permissions = permissions
        self.action_log = action_log
        self.logger = logging.getLogger(__name__)

    def execute(
        self,
        plan: ActionPlan,
        catalog: EntityCatalog,
        *,
        user_text: str,
    ) -> PlanExecutionResult:
        """Execute steps in order, stopping after a required failure."""
        outcomes: list[StepExecutionResult] = []
        for step in plan.steps:
            observation = self.validator.observe(step.entity_ids)
            previous = observation.states
            previous_attributes = observation.attributes
            if observation.status is VerificationStatus.UNAVAILABLE:
                outcome = StepExecutionResult(
                    step=step,
                    status=StepExecutionStatus.FAILED,
                    previous_states=previous,
                    observed_states=previous,
                    previous_attributes=previous_attributes,
                    observed_attributes=previous_attributes,
                    error=observation.error,
                )
                outcomes.append(outcome)
                self._log(user_text, plan, outcome)
                if not step.optional:
                    break
                continue
            runtime_step = self._with_runtime_expectations(step, previous)
            if self._is_no_op(runtime_step, previous, previous_attributes):
                outcome = StepExecutionResult(
                    step=runtime_step,
                    status=StepExecutionStatus.SKIPPED,
                    previous_states=previous,
                    observed_states=previous,
                    previous_attributes=previous_attributes,
                    observed_attributes=previous_attributes,
                )
                outcomes.append(outcome)
                self._log(user_text, plan, outcome)
                continue

            payload: dict[str, Any] = {
                **runtime_step.data,
                "entity_id": runtime_step.entity_ids,
            }
            service_result = self.services.call(
                runtime_step.domain,
                runtime_step.service,
                payload,
            )
            if not service_result.ok:
                outcome = StepExecutionResult(
                    step=runtime_step,
                    status=StepExecutionStatus.FAILED,
                    previous_states=previous,
                    observed_states={},
                    previous_attributes=previous_attributes,
                    service_called=True,
                    error=service_result.error
                    or "Home-Assistant-Service fehlgeschlagen.",
                )
                outcomes.append(outcome)
                self._log(user_text, plan, outcome)
                if not step.optional:
                    break
                continue

            verification = self.validator.verify(
                runtime_step,
                previous_attributes=previous_attributes,
            )
            status = {
                VerificationStatus.VERIFIED: StepExecutionStatus.VERIFIED,
                VerificationStatus.ACCEPTED: StepExecutionStatus.ACCEPTED,
                VerificationStatus.MISMATCH: StepExecutionStatus.FAILED,
                VerificationStatus.UNAVAILABLE: StepExecutionStatus.UNVERIFIED,
            }[verification.status]
            outcome = StepExecutionResult(
                step=runtime_step,
                status=status,
                previous_states=previous,
                observed_states=verification.states,
                previous_attributes=previous_attributes,
                observed_attributes=verification.attributes,
                service_called=True,
                error=verification.error,
            )
            outcomes.append(outcome)
            self._log(user_text, plan, outcome)
            if status in {StepExecutionStatus.FAILED, StepExecutionStatus.UNVERIFIED}:
                if not step.optional:
                    break

        return PlanExecutionResult(plan=plan, steps=tuple(outcomes))

    def _is_no_op(
        self,
        step: PlanStep,
        current_states: dict[str, str],
        current_attributes: dict[str, dict[str, Any]],
    ) -> bool:
        if step.expected_states and not all(
            current_states.get(entity_id) == expected
            for entity_id, expected in step.expected_states.items()
        ):
            return False
        attribute_match = _attribute_expectations_match(step, current_attributes)
        if attribute_match is not None:
            return attribute_match
        return bool(step.expected_states)

    def _with_runtime_expectations(
        self,
        step: PlanStep,
        current_states: dict[str, str],
    ) -> PlanStep:
        if step.service != "toggle" or step.expected_states:
            return step
        expected: dict[str, str] = {}
        for entity_id in step.entity_ids:
            current = current_states.get(entity_id)
            if current not in {"on", "off"}:
                return step
            expected[entity_id] = "off" if current == "on" else "on"
        return step.model_copy(update={"expected_states": expected})

    def _log(
        self,
        user_text: str,
        plan: ActionPlan,
        outcome: StepExecutionResult,
    ) -> None:
        step = outcome.step
        risk = self.permissions.risk_level(step.domain)
        self.action_log.append(
            user_text=user_text,
            intent=plan.intent,
            entities=step.entity_ids,
            service_call={
                "domain": step.domain,
                "service": step.service,
                "data": {**step.data, "entity_id": step.entity_ids},
                "plan_id": plan.id,
                "reason": step.reason,
            },
            risk_level=str(risk),
            auto_executed=outcome.service_called,
            result=str(outcome.status),
            error=outcome.error,
            previous_states=outcome.previous_states,
            new_states=outcome.observed_states,
        )
        self.logger.info(
            "Agent step result: plan=%s step=%s service=%s.%s status=%s",
            plan.id,
            step.id,
            step.domain,
            step.service,
            outcome.status,
        )


def _brightness_matches(attributes: dict[str, Any], brightness_pct: float) -> bool:
    brightness = _number(attributes.get("brightness"))
    if brightness is None:
        return False
    current_pct = brightness / 255 * 100
    return abs(current_pct - float(brightness_pct)) <= 2


def _attribute_expectations_match(
    step: PlanStep,
    attributes: dict[str, dict[str, Any]],
    *,
    previous_attributes: dict[str, dict[str, Any]] | None = None,
) -> bool | None:
    checks: list[bool] = []
    brightness = _number(step.data.get("brightness_pct"))
    if brightness is not None:
        checks.extend(
            _brightness_matches(attributes.get(entity_id, {}), brightness)
            for entity_id in step.entity_ids
        )

    brightness_step = _number(step.data.get("brightness_step_pct"))
    if brightness_step is not None:
        baselines = previous_attributes or {}
        for entity_id in step.entity_ids:
            before = _number(baselines.get(entity_id, {}).get("brightness"))
            after = _number(attributes.get(entity_id, {}).get("brightness"))
            if before is None or after is None:
                checks.append(False)
                continue
            expected = max(0.0, min(255.0, before + brightness_step * 2.55))
            checks.append(abs(after - expected) <= 6)

    color_temperature = _number(step.data.get("color_temp_kelvin"))
    if color_temperature is not None:
        checks.extend(
            _color_temperature_matches(
                attributes.get(entity_id, {}),
                color_temperature,
            )
            for entity_id in step.entity_ids
        )

    temperature = _number(step.data.get("temperature"))
    if temperature is not None:
        checks.extend(
            _temperature_matches(attributes.get(entity_id, {}), temperature)
            for entity_id in step.entity_ids
        )
    return all(checks) if checks else None


def _color_temperature_matches(
    attributes: dict[str, Any],
    expected_kelvin: float,
) -> bool:
    actual = _number(attributes.get("color_temp_kelvin"))
    if actual is None:
        mired = _number(attributes.get("color_temp"))
        if mired is not None and mired > 0:
            actual = 1_000_000 / mired
    return actual is not None and abs(actual - expected_kelvin) <= 150


def _temperature_matches(attributes: dict[str, Any], expected: float) -> bool:
    actual = _number(attributes.get("temperature"))
    return actual is not None and abs(actual - expected) <= 0.5


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None
