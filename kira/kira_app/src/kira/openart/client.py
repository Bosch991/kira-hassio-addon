"""OpenArt API boundary."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx


class OpenArtStatus(StrEnum):
    """Possible outcomes of OpenArt requests."""

    SUCCESS = "success"
    NOT_CONFIGURED = "not_configured"
    AUTHENTICATION_ERROR = "authentication_error"
    MISSING_KIRA_IDS = "missing_kira_ids"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"


@dataclass(frozen=True, slots=True)
class OpenArtResult:
    """Structured result returned by the OpenArt client."""

    status: OpenArtStatus
    data: Any = None
    path: Path | None = None
    error: str | None = None
    status_code: int | None = None

    @property
    def ok(self) -> bool:
        """Return whether the request succeeded."""
        return self.status is OpenArtStatus.SUCCESS


@dataclass(frozen=True, slots=True)
class OpenArtKiraConfig:
    """Configuration for the existing Kira assets in OpenArt."""

    model_id: str | None = None
    style_id: str | None = None
    world_id: str | None = None
    default_project_id: str | None = None

    @property
    def missing_ids(self) -> list[str]:
        """Return missing required Kira asset identifiers."""
        missing: list[str] = []
        if not self.model_id:
            missing.append("OPENART_KIRA_MODEL_ID")
        if not self.style_id:
            missing.append("OPENART_KIRA_STYLE_ID")
        if not self.world_id:
            missing.append("OPENART_KIRA_WORLD_ID")
        return missing


class OpenArtClient:
    """OpenArt client for account, project, model, and image workflows."""

    def __init__(
        self,
        api_key: str | None,
        *,
        kira_config: OpenArtKiraConfig | None = None,
        output_dir: Path | None = None,
        base_url: str = "https://api.openart.ai/v1",
        timeout: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the client with credentials and Kira asset IDs."""
        self.api_key = api_key
        self.kira_config = kira_config or OpenArtKiraConfig()
        self.output_dir = output_dir or Path("data/openart")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.http_client = http_client

    @property
    def is_configured(self) -> bool:
        """Return whether an OpenArt API key is available."""
        return bool(self.api_key)

    def account(self) -> OpenArtResult:
        """Fetch account information."""
        return self._request_json("GET", "/account")

    def projects(self) -> OpenArtResult:
        """Fetch OpenArt projects."""
        return self._request_json("GET", "/projects")

    def models(self) -> OpenArtResult:
        """Fetch available OpenArt models."""
        return self._request_json("GET", "/models")

    def kira_info(self) -> OpenArtResult:
        """Return locally configured Kira OpenArt IDs."""
        return OpenArtResult(
            status=OpenArtStatus.SUCCESS,
            data={
                "model_id": self.kira_config.model_id,
                "style_id": self.kira_config.style_id,
                "world_id": self.kira_config.world_id,
                "default_project_id": self.kira_config.default_project_id,
                "missing": self.kira_config.missing_ids,
            },
        )

    def generate(self, prompt: str) -> OpenArtResult:
        """Generate an image with the configured Kira model/style/world."""
        if not self.is_configured:
            return OpenArtResult(
                status=OpenArtStatus.NOT_CONFIGURED,
                error="OPENART_API_KEY is missing.",
            )
        missing = self.kira_config.missing_ids
        if missing:
            return OpenArtResult(
                status=OpenArtStatus.MISSING_KIRA_IDS,
                error=f"Missing OpenArt Kira IDs: {', '.join(missing)}.",
                data={"missing": missing},
            )
        if not prompt.strip():
            return OpenArtResult(
                status=OpenArtStatus.API_ERROR,
                error="OpenArt prompt is empty.",
            )

        payload = {
            "prompt": prompt,
            "model_id": self.kira_config.model_id,
            "style_id": self.kira_config.style_id,
            "world_id": self.kira_config.world_id,
            "project_id": self.kira_config.default_project_id,
        }
        result = self._request_json("POST", "/generations", json=payload)
        if not result.ok:
            return result
        return self._save_generation(result.data)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> OpenArtResult:
        if not self.is_configured:
            return OpenArtResult(
                status=OpenArtStatus.NOT_CONFIGURED,
                error="OPENART_API_KEY is missing.",
            )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}{path}"
        try:
            if self.http_client is not None:
                response = self.http_client.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    timeout=self.timeout,
                )
            else:
                response = httpx.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    timeout=self.timeout,
                )
            return self._parse_json_response(response)
        except httpx.TimeoutException as exc:
            return OpenArtResult(status=OpenArtStatus.TIMEOUT, error=str(exc))
        except httpx.RequestError as exc:
            return OpenArtResult(status=OpenArtStatus.NETWORK_ERROR, error=str(exc))

    def _parse_json_response(self, response: httpx.Response) -> OpenArtResult:
        if response.status_code in {401, 403}:
            return OpenArtResult(
                status=OpenArtStatus.AUTHENTICATION_ERROR,
                error="OpenArt API key was rejected.",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            return OpenArtResult(
                status=OpenArtStatus.API_ERROR,
                error=response.text,
                status_code=response.status_code,
            )
        try:
            data = response.json()
        except ValueError:
            data = {"text": response.text}
        return OpenArtResult(
            status=OpenArtStatus.SUCCESS,
            data=data,
            status_code=response.status_code,
        )

    def _save_generation(self, data: Any) -> OpenArtResult:
        image_url = self._first_image_url(data)
        image_b64 = self._first_image_b64(data)
        if image_url is None and image_b64 is None:
            return OpenArtResult(status=OpenArtStatus.SUCCESS, data=data)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = self.output_dir / f"kira-openart-{timestamp}.png"
        if image_b64 is not None:
            path.write_bytes(base64.b64decode(image_b64))
        elif image_url is not None:
            try:
                self._download_image(image_url, path)
            except httpx.TimeoutException as exc:
                return OpenArtResult(status=OpenArtStatus.TIMEOUT, error=str(exc))
            except httpx.RequestError as exc:
                return OpenArtResult(
                    status=OpenArtStatus.NETWORK_ERROR,
                    error=str(exc),
                )
            except httpx.HTTPStatusError as exc:
                return OpenArtResult(
                    status=OpenArtStatus.API_ERROR,
                    error=f"OpenArt image download failed: {exc.response.status_code}",
                    status_code=exc.response.status_code,
                )
        return OpenArtResult(status=OpenArtStatus.SUCCESS, data=data, path=path)

    def _download_image(self, url: str, path: Path) -> None:
        if self.http_client is not None:
            response = self.http_client.get(url, timeout=self.timeout)
        else:
            response = httpx.get(url, timeout=self.timeout)
        response.raise_for_status()
        path.write_bytes(response.content)

    def _first_image_url(self, data: Any) -> str | None:
        for key in ("image_url", "url"):
            if isinstance(data, dict) and isinstance(data.get(key), str):
                return data[key]
        images = data.get("images") if isinstance(data, dict) else None
        if isinstance(images, list):
            for image in images:
                if isinstance(image, dict):
                    url = image.get("url") or image.get("image_url")
                    if isinstance(url, str):
                        return url
        return None

    def _first_image_b64(self, data: Any) -> str | None:
        for key in ("image_base64", "b64_json", "base64"):
            if isinstance(data, dict) and isinstance(data.get(key), str):
                return data[key]
        images = data.get("images") if isinstance(data, dict) else None
        if isinstance(images, list):
            for image in images:
                if isinstance(image, dict):
                    value = image.get("b64_json") or image.get("base64")
                    if isinstance(value, str):
                        return value
        return None
