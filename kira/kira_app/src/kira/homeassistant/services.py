"""Home Assistant service-call layer."""

from __future__ import annotations

import logging
from typing import Any

from kira.homeassistant.client import HomeAssistantClient, HomeAssistantResult


class HomeAssistantServices:
    """Typed service layer for Home Assistant domain services."""

    def __init__(self, client: HomeAssistantClient) -> None:
        """Initialize the service layer with an existing HA REST client."""
        self.client = client
        self.logger = logging.getLogger(__name__)

    def turn_on(self, domain: str, entity_id: str) -> HomeAssistantResult:
        """Call ``<domain>.turn_on`` for one entity."""
        return self.call(domain, "turn_on", {"entity_id": entity_id})

    def turn_off(self, domain: str, entity_id: str) -> HomeAssistantResult:
        """Call ``<domain>.turn_off`` for one entity."""
        return self.call(domain, "turn_off", {"entity_id": entity_id})

    def toggle(self, domain: str, entity_id: str) -> HomeAssistantResult:
        """Call ``<domain>.toggle`` for one entity."""
        return self.call(domain, "toggle", {"entity_id": entity_id})

    def call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
    ) -> HomeAssistantResult:
        """Call ``POST /api/services/<domain>/<service>``."""
        self.logger.info(
            "Calling Home Assistant service %s.%s for entity=%s",
            domain,
            service,
            data.get("entity_id"),
        )
        result = self.client._request(  # noqa: SLF001
            "POST",
            f"/api/services/{domain}/{service}",
            json=data,
        )
        if result.ok:
            self.logger.info(
                "Home Assistant service %s.%s completed successfully",
                domain,
                service,
            )
        else:
            self.logger.warning(
                "Home Assistant service %s.%s failed: status=%s code=%s",
                domain,
                service,
                result.status,
                result.status_code,
            )
        return result
