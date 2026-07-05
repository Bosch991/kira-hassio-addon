"""Speech-to-text boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SpeechToTextStatus(StrEnum):
    """Possible speech-to-text outcomes."""

    SUCCESS = "success"
    NOT_CONFIGURED = "not_configured"
    FILE_NOT_FOUND = "file_not_found"
    AUTHENTICATION_ERROR = "authentication_error"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"
    UNSUPPORTED_PROVIDER = "unsupported_provider"


@dataclass(frozen=True, slots=True)
class SpeechToTextResult:
    """Result of a speech-to-text request."""

    status: SpeechToTextStatus
    text: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return whether transcription succeeded."""
        return self.status is SpeechToTextStatus.SUCCESS


class SpeechToTextClient:
    """Speech-to-text client supporting OpenAI Whisper as first provider."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str | None,
    ) -> None:
        """Initialize speech-to-text settings."""
        self.provider = provider
        self.model = model
        self.api_key = api_key

    @property
    def is_configured(self) -> bool:
        """Return whether the selected STT provider is usable."""
        return self.provider == "openai" and bool(self.api_key)

    def transcribe(self, audio_path: Path) -> SpeechToTextResult:
        """Transcribe an audio file."""
        if not audio_path.exists():
            return SpeechToTextResult(
                status=SpeechToTextStatus.FILE_NOT_FOUND,
                error=f"Audio file not found: {audio_path}",
            )
        if self.provider != "openai":
            return SpeechToTextResult(
                status=SpeechToTextStatus.UNSUPPORTED_PROVIDER,
                error=f"Unsupported STT provider: {self.provider}",
            )
        if not self.api_key:
            return SpeechToTextResult(
                status=SpeechToTextStatus.NOT_CONFIGURED,
                error="OPENAI_API_KEY is required for STT_PROVIDER=openai.",
            )

        try:
            from openai import (
                APIConnectionError,
                APIError,
                AuthenticationError,
                OpenAI,
                RateLimitError,
            )
        except ImportError as exc:
            return SpeechToTextResult(
                status=SpeechToTextStatus.API_ERROR,
                error=f"OpenAI SDK is not installed: {exc}",
            )

        try:
            client = OpenAI(api_key=self.api_key)
            with audio_path.open("rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model=self.model,
                    file=audio_file,
                )
            text = getattr(response, "text", "")
            return SpeechToTextResult(
                status=SpeechToTextStatus.SUCCESS,
                text=str(text).strip(),
            )
        except AuthenticationError as exc:
            return SpeechToTextResult(
                status=SpeechToTextStatus.AUTHENTICATION_ERROR,
                error=str(exc),
            )
        except RateLimitError as exc:
            return SpeechToTextResult(
                status=SpeechToTextStatus.RATE_LIMITED,
                error=str(exc),
            )
        except APIConnectionError as exc:
            return SpeechToTextResult(
                status=SpeechToTextStatus.NETWORK_ERROR,
                error=str(exc),
            )
        except APIError as exc:
            return SpeechToTextResult(
                status=SpeechToTextStatus.API_ERROR,
                error=str(exc),
            )
