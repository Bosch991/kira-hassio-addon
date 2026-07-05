"""Compact Home Assistant house status aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kira.homeassistant.analysis import EntityView, HomeAssistantAnalyzer
from kira.homeassistant.client import HomeAssistantClient

ALARM_ENTITY_ID = "alarm_control_panel.alarmo"
DOOR_WINDOW_ENTITY_IDS = (
    "binary_sensor.fenster_kuche",
    "binary_sensor.fenster_oben",
    "binary_sensor.tur_eg",
    "binary_sensor.openclose_54",
    "binary_sensor.openclose_55",
)
PRINTER_ENTITY_IDS = (
    "sensor.anycubic_kobra_s1_current_status",
    "sensor.anycubic_kobra_s1_job_progress",
    "sensor.anycubic_kobra_s1_job_eta",
    "sensor.anycubic_kobra_s1_job_time_remaining",
    "binary_sensor.anycubic_kobra_s1_job_in_progress",
)
WEATHER_ENTITY_ID = "weather.weather_97199_ochsenfurt_deutschland"
ENERGY_ENTITY_IDS = (
    "sensor.hausverbrauch_echt",
    "sensor.powerstream_solar_1_watts",
    "sensor.powerstream_solar_2_watts",
    "sensor.powerstream_battery_charge",
)
WASHER_ENTITY_IDS = (
    "switch.shelly1pmg3_cc8da246efb4",
    "sensor.shelly1pmg3_cc8da246efb4_power",
)
RING_ENTITY_IDS = (
    "binary_sensor.klingel_klingelsensor",
    "input_datetime.letzte_klingelzeit",
)


@dataclass(frozen=True, slots=True)
class HomeStatusResult:
    """Result returned by the home status service."""

    ok: bool
    response: str


class HomeStatusService:
    """Build compact, useful status summaries from Home Assistant states."""

    def __init__(self, client: HomeAssistantClient) -> None:
        """Initialize the status service with an existing HA client."""
        self.client = client
        self.analyzer = HomeAssistantAnalyzer()

    def status(self) -> HomeStatusResult:
        """Load Home Assistant states and return a compact house status."""
        result = self.client.states()
        if not result.ok:
            return HomeStatusResult(
                ok=False,
                response=self._error_response(result.error),
            )
        if not isinstance(result.data, list):
            return HomeStatusResult(
                ok=False,
                response="Hausstatus: Home Assistant lieferte keine State-Liste.",
            )

        states = [item for item in result.data if isinstance(item, dict)]
        return HomeStatusResult(ok=True, response=self.from_states(states))

    def from_states(self, states: list[dict[str, Any]]) -> str:
        """Build a compact status response from raw state dictionaries."""
        analysis = self.analyzer.analyze(states)
        entities = {entity.entity_id: entity for entity in analysis.entities}
        sections = [
            self._alarm_status(entities),
            self._door_window_status(entities),
            self._light_status(analysis.active_lights),
            self._printer_status(entities),
            self._weather_status(entities),
            self._energy_status(entities),
            self._washer_status(entities),
            self._ring_status(entities),
        ]
        relevant = [section for section in sections if section]
        if not relevant:
            return (
                "Hausstatus: Alles ruhig. Keine offenen Tueren oder Fenster, "
                "keine kritischen Geraete."
            )
        return self._limit_response("Hausstatus: " + " ".join(relevant))

    def _alarm_status(self, entities: dict[str, EntityView]) -> str | None:
        alarm = self._valid_entity(entities, ALARM_ENTITY_ID)
        if alarm is None:
            return None
        if alarm.state in {"triggered", "triggering", "alarm"}:
            return "Alarm ist ausgeloest."
        if alarm.state == "disarmed":
            return "Alarm ist deaktiviert."
        if alarm.state.startswith("armed"):
            return "Alarm ist scharf."
        return None

    def _door_window_status(self, entities: dict[str, EntityView]) -> str | None:
        open_entities = [
            entity
            for entity_id in DOOR_WINDOW_ENTITY_IDS
            if (entity := self._valid_entity(entities, entity_id)) is not None
            and entity.state in {"on", "open"}
        ]
        if not open_entities:
            return None
        names = self._join_names([entity.label for entity in open_entities], limit=4)
        return f"Offen: {names}."

    def _light_status(self, active_lights: list[EntityView]) -> str | None:
        if not active_lights:
            return None
        names = self._join_names([entity.label for entity in active_lights], limit=5)
        count = self._number_word(len(active_lights))
        return f"{count} Lichter sind an: {names}."

    def _printer_status(self, entities: dict[str, EntityView]) -> str | None:
        in_progress = self._valid_entity(
            entities,
            "binary_sensor.anycubic_kobra_s1_job_in_progress",
        )
        current = self._valid_entity(
            entities,
            "sensor.anycubic_kobra_s1_current_status",
        )
        if in_progress is None and current is None:
            return None
        is_printing = in_progress is not None and in_progress.state == "on"
        if current is not None:
            is_printing = is_printing or "print" in current.state.lower()
        if not is_printing:
            return None

        progress = self._state(entities, "sensor.anycubic_kobra_s1_job_progress")
        remaining = self._state(
            entities,
            "sensor.anycubic_kobra_s1_job_time_remaining",
        )
        eta = self._state(entities, "sensor.anycubic_kobra_s1_job_eta")
        details = []
        if progress is not None:
            details.append(f"mit {self._format_number(progress)} Prozent")
        if remaining is not None:
            details.append(f"Restzeit etwa {self._format_duration(remaining)}")
        elif eta is not None:
            details.append(f"ETA {eta}")
        suffix = ", ".join(details)
        return f"Der Kobra S1 druckt{f' {suffix}' if suffix else ''}."

    def _weather_status(self, entities: dict[str, EntityView]) -> str | None:
        weather = self._valid_entity(entities, WEATHER_ENTITY_ID)
        if weather is None:
            return None
        attributes = weather.raw.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}
        temperature = attributes.get("temperature")
        condition = self._translate_weather(weather.state)
        if temperature in {None, ""}:
            return f"Wetter: {condition}."
        return f"Wetter: {condition} bei {self._format_number(temperature)} Grad."

    def _energy_status(self, entities: dict[str, EntityView]) -> str | None:
        house = self._state(entities, "sensor.hausverbrauch_echt")
        solar_1 = self._float_state(entities, "sensor.powerstream_solar_1_watts")
        solar_2 = self._float_state(entities, "sensor.powerstream_solar_2_watts")
        battery = self._state(entities, "sensor.powerstream_battery_charge")
        details = []
        if house is not None:
            details.append(f"Hausverbrauch {self._format_number(house)} W")
        solar = (solar_1 or 0.0) + (solar_2 or 0.0)
        if solar > 0:
            details.append(f"PV {self._format_number(solar)} W")
        if battery is not None:
            details.append(f"Akku {self._format_number(battery)} Prozent")
        if not details:
            return None
        return "Energie: " + ", ".join(details) + "."

    def _washer_status(self, entities: dict[str, EntityView]) -> str | None:
        washer = self._valid_entity(entities, "switch.shelly1pmg3_cc8da246efb4")
        power = self._float_state(entities, "sensor.shelly1pmg3_cc8da246efb4_power")
        is_active = washer is not None and washer.state == "on"
        is_active = is_active or (power is not None and power > 5)
        if not is_active:
            return None
        if power is None:
            return "Waschmaschine laeuft."
        return f"Waschmaschine laeuft mit {self._format_number(power)} W."

    def _ring_status(self, entities: dict[str, EntityView]) -> str | None:
        ring = self._valid_entity(entities, "binary_sensor.klingel_klingelsensor")
        last_ring = self._state(entities, "input_datetime.letzte_klingelzeit")
        if ring is not None and ring.state == "on":
            return "Es hat gerade geklingelt."
        if last_ring:
            return f"Letzte Klingelzeit: {last_ring}."
        return None

    def _valid_entity(
        self,
        entities: dict[str, EntityView],
        entity_id: str,
    ) -> EntityView | None:
        entity = entities.get(entity_id)
        if entity is None or entity.state in {"unknown", "unavailable", ""}:
            return None
        return entity

    def _state(self, entities: dict[str, EntityView], entity_id: str) -> str | None:
        entity = self._valid_entity(entities, entity_id)
        return entity.state if entity is not None else None

    def _float_state(
        self,
        entities: dict[str, EntityView],
        entity_id: str,
    ) -> float | None:
        value = self._state(entities, entity_id)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _join_names(self, names: list[str], *, limit: int) -> str:
        visible = names[:limit]
        joined = ", ".join(visible)
        remaining = len(names) - len(visible)
        if remaining > 0:
            joined = f"{joined} und {remaining} weitere"
        return joined

    def _number_word(self, value: int) -> str:
        words = {
            1: "Ein",
            2: "Zwei",
            3: "Drei",
            4: "Vier",
            5: "Fuenf",
        }
        return words.get(value, str(value))

    def _format_number(self, value: object) -> str:
        try:
            number = float(str(value))
        except ValueError:
            return str(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:.1f}".rstrip("0").rstrip(".")

    def _format_duration(self, value: str) -> str:
        parts = value.split(":")
        if len(parts) >= 2 and all(part.isdigit() for part in parts[:2]):
            hours = int(parts[0])
            minutes = int(parts[1])
            if hours and minutes:
                return f"{hours} Stunden {minutes} Minuten"
            if hours:
                return f"{hours} Stunden"
            return f"{minutes} Minuten"
        return value

    def _translate_weather(self, condition: str) -> str:
        translations = {
            "cloudy": "bewoelkt",
            "partlycloudy": "teilweise bewoelkt",
            "sunny": "sonnig",
            "rainy": "regnerisch",
            "pouring": "starker Regen",
            "snowy": "Schnee",
            "fog": "neblig",
            "windy": "windig",
        }
        return translations.get(condition, condition)

    def _error_response(self, error: str | None) -> str:
        if error:
            return f"Hausstatus: Home Assistant ist gerade nicht erreichbar: {error}"
        return "Hausstatus: Home Assistant ist gerade nicht erreichbar."

    def _limit_response(self, response: str, *, max_length: int = 650) -> str:
        if len(response) <= max_length:
            return response
        return response[: max_length - 1].rstrip(" ,.;") + "."
