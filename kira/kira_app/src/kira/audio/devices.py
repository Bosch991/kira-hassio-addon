"""Audio device discovery and persisted selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AudioDevice:
    """A local audio device."""

    index: int
    name: str
    is_input: bool
    is_output: bool
    is_default_input: bool = False
    is_default_output: bool = False


@dataclass(slots=True)
class AudioSettings:
    """Persisted audio routing settings."""

    mode: str = "local"
    input_device: str | None = None
    output_device: str | None = None
    ha_media_player: str | None = None


class AudioDeviceManager:
    """List and persist local audio device selections."""

    def __init__(self, settings_path: Path) -> None:
        """Initialize the manager with its settings file."""
        self.settings_path = settings_path

    def list_devices(self) -> list[AudioDevice]:
        """Return local audio devices reported by sounddevice."""
        try:
            import sounddevice as sd
        except ModuleNotFoundError:
            return []

        default_input, default_output = self._default_device_indexes(sd)
        devices: list[AudioDevice] = []
        for index, raw_device in enumerate(sd.query_devices()):
            device = dict(raw_device)
            max_input_channels = int(device.get("max_input_channels", 0))
            max_output_channels = int(device.get("max_output_channels", 0))
            devices.append(
                AudioDevice(
                    index=index,
                    name=str(device.get("name", f"Device {index}")),
                    is_input=max_input_channels > 0,
                    is_output=max_output_channels > 0,
                    is_default_input=index == default_input,
                    is_default_output=index == default_output,
                )
            )
        return devices

    def list_input_devices(self) -> list[AudioDevice]:
        """Return input-capable devices."""
        return [device for device in self.list_devices() if device.is_input]

    def list_output_devices(self) -> list[AudioDevice]:
        """Return output-capable devices."""
        return [device for device in self.list_devices() if device.is_output]

    def load_settings(self) -> AudioSettings:
        """Load persisted audio settings."""
        if not self.settings_path.exists():
            return AudioSettings()
        data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        return AudioSettings(
            mode=str(data.get("mode", "local")),
            input_device=data.get("input_device"),
            output_device=data.get("output_device"),
            ha_media_player=data.get("ha_media_player"),
        )

    def save_settings(self, settings: AudioSettings) -> None:
        """Persist audio settings."""
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "mode": settings.mode,
            "input_device": settings.input_device,
            "output_device": settings.output_device,
            "ha_media_player": settings.ha_media_player,
        }
        self.settings_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def select_input(self, selector: str) -> AudioSettings:
        """Select and persist an input device by index or name."""
        return self._select_device(selector=selector, direction="input")

    def select_output(self, selector: str) -> AudioSettings:
        """Select and persist an output device by index or name."""
        return self._select_device(selector=selector, direction="output")

    def set_mode(self, mode: str) -> AudioSettings:
        """Persist audio output mode."""
        if mode not in {"local", "ha"}:
            raise ValueError(f"Unsupported audio mode: {mode}")
        settings = self.load_settings()
        settings.mode = mode
        self.save_settings(settings)
        return settings

    def set_ha_media_player(self, entity_id: str) -> AudioSettings:
        """Persist the Home Assistant media player target."""
        settings = self.load_settings()
        settings.ha_media_player = entity_id
        self.save_settings(settings)
        return settings

    def _select_device(self, *, selector: str, direction: str) -> AudioSettings:
        devices = (
            self.list_input_devices()
            if direction == "input"
            else self.list_output_devices()
        )
        device = self._find_device(devices, selector)
        if device is None:
            raise ValueError(f"Audio device not found: {selector}")

        settings = self.load_settings()
        if direction == "input":
            settings.input_device = str(device.index)
        else:
            settings.output_device = str(device.index)
        self.save_settings(settings)
        return settings

    def _find_device(
        self,
        devices: list[AudioDevice],
        selector: str,
    ) -> AudioDevice | None:
        selector = selector.strip()
        if selector.isdigit():
            index = int(selector)
            return next((device for device in devices if device.index == index), None)

        needle = selector.lower()
        return next(
            (device for device in devices if needle in device.name.lower()), None
        )

    def _default_device_indexes(self, sounddevice_module: Any) -> tuple[int, int]:
        default = getattr(sounddevice_module, "default", None)
        device = getattr(default, "device", (-1, -1))
        if isinstance(device, list | tuple) and len(device) >= 2:
            return int(device[0]), int(device[1])
        return -1, -1
