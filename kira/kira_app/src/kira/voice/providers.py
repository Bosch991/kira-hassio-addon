"""Voice provider boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx


class VoiceStatus(StrEnum):
    """Possible outcomes of voice generation."""

    SUCCESS = "success"
    NOT_CONFIGURED = "not_configured"
    AUTHENTICATION_ERROR = "authentication_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"
    VOICE_NOT_FOUND = "voice_not_found"


@dataclass(frozen=True, slots=True)
class VoiceResult:
    """Structured result returned by a voice provider."""

    status: VoiceStatus
    path: Path | None = None
    data: Any = None
    error: str | None = None
    status_code: int | None = None

    @property
    def ok(self) -> bool:
        """Return whether voice generation succeeded."""
        return self.status is VoiceStatus.SUCCESS


class ElevenLabsVoiceProvider:
    """ElevenLabs text-to-speech provider writing MP3 files locally."""

    def __init__(
        self,
        api_key: str | None,
        voice_id: str | None,
        output_dir: Path,
        *,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the provider with credentials and output settings."""
        self.api_key = api_key
        self.voice_id = voice_id
        self.output_dir = output_dir
        self.timeout = timeout
        self.http_client = http_client

    @property
    def is_configured(self) -> bool:
        """Return whether ElevenLabs credentials are available."""
        return bool(self.api_key and self.voice_id)

    def text_to_speech(self, text: str) -> VoiceResult:
        """Generate an MP3 file for the provided text."""
        if not self.is_configured:
            return VoiceResult(
                status=VoiceStatus.NOT_CONFIGURED,
                error="ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID is missing.",
            )
        if not text.strip():
            return VoiceResult(
                status=VoiceStatus.API_ERROR,
                error="Text for speech generation is empty.",
            )

        assert self.voice_id is not None
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": str(self.api_key),
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
        }

        try:
            if self.http_client is not None:
                response = self.http_client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
            else:
                response = httpx.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
            return self._save_response(response)
        except httpx.TimeoutException as exc:
            return VoiceResult(status=VoiceStatus.TIMEOUT, error=str(exc))
        except httpx.RequestError as exc:
            return VoiceResult(status=VoiceStatus.NETWORK_ERROR, error=str(exc))

    def list_voices(self) -> VoiceResult:
        """Fetch available ElevenLabs voices for the configured account."""
        if not self.api_key:
            return VoiceResult(
                status=VoiceStatus.NOT_CONFIGURED,
                error="ELEVENLABS_API_KEY is missing.",
            )

        headers = {"xi-api-key": str(self.api_key)}
        url = "https://api.elevenlabs.io/v1/voices"
        try:
            if self.http_client is not None:
                response = self.http_client.get(
                    url,
                    headers=headers,
                    timeout=self.timeout,
                )
            else:
                response = httpx.get(url, headers=headers, timeout=self.timeout)
            return self._parse_json_response(response)
        except httpx.TimeoutException as exc:
            return VoiceResult(status=VoiceStatus.TIMEOUT, error=str(exc))
        except httpx.RequestError as exc:
            return VoiceResult(status=VoiceStatus.NETWORK_ERROR, error=str(exc))

    def _save_response(self, response: httpx.Response) -> VoiceResult:
        if response.status_code in {401, 403}:
            return VoiceResult(
                status=VoiceStatus.AUTHENTICATION_ERROR,
                error="ElevenLabs API key was rejected.",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            error_code = self._error_code(response)
            if error_code == "voice_not_found":
                return VoiceResult(
                    status=VoiceStatus.VOICE_NOT_FOUND,
                    error="ElevenLabs voice id was not found for this account.",
                    status_code=response.status_code,
                )
            return VoiceResult(
                status=VoiceStatus.API_ERROR,
                error=response.text,
                status_code=response.status_code,
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = self.output_dir / f"kira-{timestamp}.mp3"
        path.write_bytes(response.content)
        return VoiceResult(
            status=VoiceStatus.SUCCESS,
            path=path,
            status_code=response.status_code,
        )

    def _parse_json_response(self, response: httpx.Response) -> VoiceResult:
        if response.status_code in {401, 403}:
            return VoiceResult(
                status=VoiceStatus.AUTHENTICATION_ERROR,
                error="ElevenLabs API key was rejected.",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            return VoiceResult(
                status=VoiceStatus.API_ERROR,
                error=response.text,
                status_code=response.status_code,
            )

        return VoiceResult(
            status=VoiceStatus.SUCCESS,
            data=response.json(),
            status_code=response.status_code,
        )

    def _error_code(self, response: httpx.Response) -> str | None:
        try:
            payload: dict[str, Any] = response.json()
        except ValueError:
            return None
        detail = payload.get("detail")
        if isinstance(detail, dict):
            code = detail.get("code")
            return code if isinstance(code, str) else None
        return None


class PiperVoiceProvider:
    """Placeholder for future local Piper text-to-speech support."""

    @property
    def is_available(self) -> bool:
        """Return whether Piper is available on this system."""
        return False
