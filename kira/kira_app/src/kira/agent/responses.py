"""Short, natural responses grounded in Home Assistant results."""

from __future__ import annotations

from typing import Any

from kira.agent.entities import EntityDescriptor, EntityResolution
from kira.agent.execution import (
    PlanExecutionResult,
    StepExecutionResult,
    StepExecutionStatus,
)
from kira.agent.models import ActionPlan, AgentIntent, MetricType


class QueryResponseBuilder:
    """Format resolved Home Assistant values without involving a language model."""

    def build(self, intent: AgentIntent, resolution: EntityResolution) -> str:
        """Return a concise answer grounded in matching entity states."""
        if not resolution.matches:
            if intent.state_filter:
                return "Keine passenden Geraete sind gerade in diesem Zustand."
            target = intent.target or intent.metric.value
            return f"Ich finde fuer '{target}' gerade keinen passenden HA-Wert."
        lines = [
            self._entity_value(intent.metric, entity) for entity in resolution.matches
        ]
        unique = list(dict.fromkeys(line for line in lines if line))
        if not unique:
            return "Die passende Entity hat gerade keinen lesbaren Wert."
        response = " ".join(unique[:5])
        if len(unique) > 5:
            response = f"{response} Noch {len(unique) - 5} weitere."
        return response

    def _entity_value(self, metric: MetricType, entity: EntityDescriptor) -> str:
        binary_value = self._binary_value(entity)
        if metric in {MetricType.NONE, MetricType.STATE} and binary_value is not None:
            return f"{entity.name}: {binary_value}."
        if entity.domain == "weather" and metric in {
            MetricType.NONE,
            MetricType.STATE,
        }:
            return self._weather_value(entity)
        value, unit = self._value(metric, entity)
        if metric is MetricType.TEMPERATURE and "outside" in entity.tags:
            return f"Draussen sind es {_format_value(value, unit, metric)}."
        return f"{entity.name}: {_format_value(value, unit, metric)}."

    def _binary_value(self, entity: EntityDescriptor) -> str | None:
        if entity.domain != "binary_sensor":
            return None
        device_class = str(entity.device_class or "")
        state = entity.state.lower()
        states_by_class = {
            "door": {"on": "offen", "off": "geschlossen"},
            "garage_door": {"on": "offen", "off": "geschlossen"},
            "opening": {"on": "offen", "off": "geschlossen"},
            "window": {"on": "offen", "off": "geschlossen"},
            "motion": {"on": "Bewegung erkannt", "off": "keine Bewegung"},
            "occupancy": {"on": "belegt", "off": "frei"},
            "presence": {"on": "anwesend", "off": "abwesend"},
            "moisture": {"on": "nass", "off": "trocken"},
            "problem": {"on": "Problem erkannt", "off": "in Ordnung"},
            "safety": {"on": "unsicher", "off": "sicher"},
        }
        return states_by_class.get(device_class, {}).get(state)

    def _weather_value(self, entity: EntityDescriptor) -> str:
        condition = {
            "clear-night": "klar",
            "cloudy": "bewoelkt",
            "fog": "neblig",
            "partlycloudy": "teilweise bewoelkt",
            "pouring": "starker Regen",
            "rainy": "regnerisch",
            "snowy": "Schnee",
            "sunny": "sonnig",
            "windy": "windig",
        }.get(entity.state, entity.state)
        temperature = entity.attributes.get("temperature")
        if temperature not in {None, ""}:
            formatted_temperature = str(temperature).replace(".", ",")
            return f"{entity.name}: {condition}, {formatted_temperature} Grad."
        return f"{entity.name}: {condition}."

    def _value(
        self,
        metric: MetricType,
        entity: EntityDescriptor,
    ) -> tuple[Any, str | None]:
        attributes = entity.attributes
        attribute_names: dict[MetricType, tuple[str, ...]] = {
            MetricType.TEMPERATURE: ("temperature", "current_temperature"),
            MetricType.HUMIDITY: ("humidity",),
            MetricType.BATTERY: ("battery_level", "battery"),
            MetricType.POWER: ("power",),
            MetricType.ENERGY: ("energy",),
            MetricType.PRESSURE: ("pressure",),
        }
        for name in attribute_names.get(metric, ()):
            value = attributes.get(name)
            if value not in {None, ""}:
                unit = entity.unit or _default_unit(metric, attributes)
                return value, unit
        return entity.state, entity.unit or _default_unit(metric, attributes)


class ActionResponseBuilder:
    """Summarize plans and verified execution outcomes naturally."""

    def confirmation(self, plan: ActionPlan, *, entity_names: list[str]) -> str:
        """Describe an awaiting plan without exposing raw service jargon."""
        target = _join_names(entity_names, limit=5) or "mehrere Geraete"
        return (
            f"Mein Plan fuer '{plan.goal}' hat {len(plan.steps)} Schritt(e) und "
            f"betrifft {target}. Das braucht deine Bestaetigung. "
            "Antworte mit 'Bestaetigen' oder 'Abbrechen'."
        )

    def execution(
        self,
        result: PlanExecutionResult,
        *,
        entity_names: dict[str, str],
    ) -> str:
        """Return a short result that distinguishes proof from assumption."""
        if not result.steps:
            return "Der Plan enthielt keine ausfuehrbare Aktion."
        failed = [
            item for item in result.steps if item.status is StepExecutionStatus.FAILED
        ]
        unverified = [
            item
            for item in result.steps
            if item.status is StepExecutionStatus.UNVERIFIED
        ]
        accepted = [
            item for item in result.steps if item.status is StepExecutionStatus.ACCEPTED
        ]
        changed = [
            item for item in result.steps if item.status is StepExecutionStatus.VERIFIED
        ]
        skipped = [
            item for item in result.steps if item.status is StepExecutionStatus.SKIPPED
        ]
        if failed:
            names = self._outcome_names(failed, entity_names)
            detail = failed[0].error or "Der Zielzustand wurde nicht erreicht."
            prefix = self._verified_prefix(changed, entity_names)
            failure = f"Bei {names} hat es nicht geklappt: {detail}"
            return f"{prefix} {failure}".strip()
        if unverified:
            names = self._outcome_names(unverified, entity_names)
            prefix = self._verified_prefix(changed, entity_names)
            warning = (
                f"Befehl fuer {names} wurde gesendet, aber ich konnte den "
                "neuen Zustand nicht bestaetigen."
            )
            return f"{prefix} {warning}".strip()
        if accepted:
            prefix = self._verified_prefix(changed, entity_names)
            names = self._outcome_names(accepted, entity_names)
            acknowledgement = (
                f"{names} wurde ausgeloest. Die Auswirkungen kann ich nicht "
                "vollstaendig verifizieren."
            )
            return f"{prefix} {acknowledgement}".strip()
        if changed:
            descriptions = [self._step_success(item, entity_names) for item in changed]
            prefix = " ".join(descriptions)
            if skipped:
                unchanged = self._outcome_names(skipped, entity_names)
                return f"{prefix} {unchanged} war bereits passend eingestellt."
            return prefix
        names = self._outcome_names(skipped, entity_names)
        return f"{names} war bereits passend eingestellt."

    def _verified_prefix(
        self,
        outcomes: list[StepExecutionResult],
        entity_names: dict[str, str],
    ) -> str:
        return " ".join(self._step_success(item, entity_names) for item in outcomes)

    def _step_success(
        self,
        outcome: StepExecutionResult,
        entity_names: dict[str, str],
    ) -> str:
        names = _join_names(
            [
                entity_names.get(entity_id, entity_id)
                for entity_id in outcome.step.entity_ids
            ],
            limit=5,
        )
        service = outcome.step.service
        if service == "turn_on" and "brightness_step_pct" in outcome.step.data:
            direction = (
                "dunkler"
                if float(outcome.step.data["brightness_step_pct"]) < 0
                else "heller"
            )
            return f"{names} ist jetzt {direction}."
        if service == "turn_on" and "color_temp_kelvin" in outcome.step.data:
            return f"{names} hat jetzt die gewuenschte Lichttemperatur."
        translations = {
            "turn_on": "ist an",
            "turn_off": "ist aus",
            "open_cover": "ist offen",
            "close_cover": "ist geschlossen",
            "lock": "ist verriegelt",
            "unlock": "ist entriegelt",
            "media_play": "laeuft",
            "media_pause": "ist pausiert",
            "media_stop": "ist gestoppt",
            "trigger": "wurde ausgeloest",
        }
        return f"{names} {translations.get(service, 'ist eingestellt')}."

    def _outcome_names(
        self,
        outcomes: list[StepExecutionResult],
        entity_names: dict[str, str],
    ) -> str:
        names = [
            entity_names.get(entity_id, entity_id)
            for outcome in outcomes
            for entity_id in outcome.step.entity_ids
        ]
        return _join_names(list(dict.fromkeys(names)), limit=5)


def plan_entity_names(plan: ActionPlan, names: dict[str, str]) -> list[str]:
    """Return unique friendly names used by a plan."""
    return list(
        dict.fromkeys(
            names.get(entity_id, entity_id)
            for step in plan.steps
            for entity_id in step.entity_ids
        )
    )


def _format_value(value: Any, unit: str | None, metric: MetricType) -> str:
    state = str(value)
    translations = {
        "on": "an",
        "off": "aus",
        "open": "offen",
        "closed": "geschlossen",
        "locked": "verriegelt",
        "unlocked": "entriegelt",
        "playing": "laeuft",
        "paused": "pausiert",
        "idle": "bereit",
        "standby": "im Standby",
        "unavailable": "nicht verfuegbar",
        "unknown": "Zustand unbekannt",
    }
    translated = translations.get(state.lower(), state.replace(".", ","))
    if state.lower() in {"unavailable", "unknown"}:
        return translated
    if unit:
        normalized_unit = unit.lower().replace("\u00b0", "")
        if metric is MetricType.TEMPERATURE or normalized_unit in {"c", "f"}:
            return f"{translated} Grad"
        return f"{translated} {unit}"
    if metric is MetricType.TEMPERATURE:
        return f"{translated} Grad"
    if metric in {MetricType.HUMIDITY, MetricType.BATTERY}:
        return f"{translated} Prozent"
    return translated


def _default_unit(metric: MetricType, attributes: dict[str, Any]) -> str | None:
    if metric is MetricType.TEMPERATURE:
        value = attributes.get("temperature_unit")
        return str(value) if value else "C"
    if metric in {MetricType.HUMIDITY, MetricType.BATTERY}:
        return "%"
    return None


def _join_names(names: list[str], *, limit: int) -> str:
    values = names[:limit]
    if not values:
        return "die ausgewaehlten Geraete"
    if len(values) == 1:
        return values[0]
    if len(names) > limit:
        values.append(f"{len(names) - limit} weitere")
    return ", ".join(values[:-1]) + f" und {values[-1]}"
