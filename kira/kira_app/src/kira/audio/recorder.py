"""Local microphone recording."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


class RecordingStatus(StrEnum):
    """Possible recording outcomes."""

    SUCCESS = "success"
    DEPENDENCY_MISSING = "dependency_missing"
    RECORDING_ERROR = "recording_error"


@dataclass(frozen=True, slots=True)
class RecordingResult:
    """Result of a local microphone recording."""

    status: RecordingStatus
    path: Path | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return whether recording succeeded."""
        return self.status is RecordingStatus.SUCCESS


class RecorderBackend(Protocol):
    """Minimal recorder backend protocol for tests."""

    def record(
        self,
        *,
        seconds: int,
        samplerate: int,
        channels: int,
        device: str | None,
    ) -> Any:
        """Record audio and return array-like samples."""

    def write(self, path: Path, data: Any, samplerate: int) -> None:
        """Write samples to disk."""


class SoundDeviceRecorderBackend:
    """Recorder backend using sounddevice and soundfile."""

    def record(
        self,
        *,
        seconds: int,
        samplerate: int,
        channels: int,
        device: str | None,
    ) -> Any:
        """Record audio via sounddevice."""
        import sounddevice as sd

        frames = int(seconds * samplerate)
        data = sd.rec(
            frames,
            samplerate=samplerate,
            channels=channels,
            device=device or None,
        )
        sd.wait()
        return data

    def write(self, path: Path, data: Any, samplerate: int) -> None:
        """Write audio via soundfile."""
        import soundfile as sf

        sf.write(path, data, samplerate)


class AudioRecorder:
    """Record microphone audio to local WAV files."""

    def __init__(
        self,
        output_dir: Path,
        *,
        seconds: int = 8,
        input_device: str | None = None,
        samplerate: int = 16_000,
        channels: int = 1,
        backend: RecorderBackend | None = None,
    ) -> None:
        """Initialize the recorder."""
        self.output_dir = output_dir
        self.seconds = seconds
        self.input_device = input_device
        self.samplerate = samplerate
        self.channels = channels
        self.backend = backend or SoundDeviceRecorderBackend()

    def record(self) -> RecordingResult:
        """Record audio and return the saved WAV path."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = self.output_dir / f"kira-input-{timestamp}.wav"

        try:
            data = self.backend.record(
                seconds=self.seconds,
                samplerate=self.samplerate,
                channels=self.channels,
                device=self.input_device,
            )
            self.backend.write(path, data, self.samplerate)
        except ModuleNotFoundError as exc:
            return RecordingResult(
                status=RecordingStatus.DEPENDENCY_MISSING,
                error=f"Audio recording dependency missing: {exc.name}",
            )
        except Exception as exc:
            return RecordingResult(
                status=RecordingStatus.RECORDING_ERROR,
                error=str(exc),
            )

        return RecordingResult(status=RecordingStatus.SUCCESS, path=path)
