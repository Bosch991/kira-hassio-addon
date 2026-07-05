"""Home Assistant REST API client."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx


class HomeAssistantStatus(StrEnum):
    """Possible outcomes of a Home Assistant request."""

    SUCCESS = "success"
    NOT_CONFIGURED = "not_configured"
    AUTHENTICATION_ERROR = "authentication_error"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"


@dataclass(frozen=True, slots=True)
class HomeAssistantResult:
    """Structured result returned by the Home Assistant client."""

    status: HomeAssistantStatus
    data: Any = None
    error: str | None = None
    status_code: int | None = None

    @property
    def ok(self) -> bool:
        """Return whether the request was successful."""
        return self.status is HomeAssistantStatus.SUCCESS


@dataclass(frozen=True, slots=True)
class HomeAssistantSummary:
    """Short overview of Home Assistant entities."""

    total_entities: int
    lights: int
    switches: int
    sensors: int
    unavailable: int
    unknown: int


class HomeAssistantClient:
    """Small REST boundary around Home Assistant."""

    def __init__(
        self,
        base_url: str | None,
        token: str | None,
        *,
        timeout: float = 10.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the client with credentials and HTTP settings."""
        self.base_url = base_url.rstrip("/") if base_url else None
        self.token = token
        self.timeout = timeout
        self.http_client = http_client

    @property
    def is_configured(self) -> bool:
        """Return whether Home Assistant credentials are available."""
        return bool(self.base_url and self.token)

    def ping(self) -> HomeAssistantResult:
        """Call GET /api/."""
        return self._request("GET", "/api/")

    def config(self) -> HomeAssistantResult:
        """Call GET /api/config."""
        return self._request("GET", "/api/config")

    def states(self) -> HomeAssistantResult:
        """Call GET /api/states."""
        return self._request("GET", "/api/states")

    def entity(self, entity_id: str) -> HomeAssistantResult:
        """Call GET /api/states/{entity_id}."""
        return self._request("GET", f"/api/states/{entity_id}")

    def call_service(
        self,
        *,
        domain: str,
        service: str,
        entity_id: str,
    ) -> HomeAssistantResult:
        """Call POST /api/services/{domain}/{service} for one entity."""
        return self._request(
            "POST",
            f"/api/services/{domain}/{service}",
            json={"entity_id": entity_id},
        )

    def play_media(
        self,
        *,
        entity_id: str,
        media_content_id: str,
        media_content_type: str,
    ) -> HomeAssistantResult:
        """Play media on a Home Assistant media_player entity."""
        return self._request(
            "POST",
            "/api/services/media_player/play_media",
            json={
                "entity_id": entity_id,
                "media_content_id": media_content_id,
                "media_content_type": media_content_type,
            },
        )

    def summary(self) -> HomeAssistantResult:
        """Return a compact summary of current Home Assistant states."""
        result = self.states()
        if not result.ok:
            return result

        if not isinstance(result.data, list):
            return HomeAssistantResult(
                status=HomeAssistantStatus.API_ERROR,
                error="Unexpected states response shape.",
            )

        domain_counts = Counter(
            str(item.get("entity_id", "")).split(".", maxsplit=1)[0]
            for item in result.data
            if isinstance(item, dict)
        )
        state_counts = Counter(
            str(item.get("state", "")) for item in result.data if isinstance(item, dict)
        )
        return HomeAssistantResult(
            status=HomeAssistantStatus.SUCCESS,
            data=HomeAssistantSummary(
                total_entities=len(result.data),
                lights=domain_counts["light"],
                switches=domain_counts["switch"],
                sensors=domain_counts["sensor"],
                unavailable=state_counts["unavailable"],
                unknown=state_counts["unknown"],
            ),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> HomeAssistantResult:
        if not self.is_configured:
            return HomeAssistantResult(
                status=HomeAssistantStatus.NOT_CONFIGURED,
                error="HOMEASSISTANT_URL or HOMEASSISTANT_TOKEN is missing.",
            )

        assert self.base_url is not None
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

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
            return self._parse_response(response)
        except httpx.TimeoutException as exc:
            return HomeAssistantResult(
                status=HomeAssistantStatus.TIMEOUT,
                error=str(exc),
            )
        except httpx.RequestError as exc:
            return HomeAssistantResult(
                status=HomeAssistantStatus.NETWORK_ERROR,
                error=str(exc),
            )

    def _parse_response(self, response: httpx.Response) -> HomeAssistantResult:
        if response.status_code == 401:
            return HomeAssistantResult(
                status=HomeAssistantStatus.AUTHENTICATION_ERROR,
                error="Home Assistant token was rejected.",
                status_code=response.status_code,
            )
        if response.status_code == 404:
            return HomeAssistantResult(
                status=HomeAssistantStatus.NOT_FOUND,
                error="Home Assistant resource was not found.",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            return HomeAssistantResult(
                status=HomeAssistantStatus.API_ERROR,
                error=response.text,
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except ValueError:
            data = response.text

        return HomeAssistantResult(
            status=HomeAssistantStatus.SUCCESS,
            data=data,
            status_code=response.status_code,
        )
