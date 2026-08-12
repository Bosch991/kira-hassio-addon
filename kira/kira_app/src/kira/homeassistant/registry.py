"""Read-only Home Assistant registry integration and entity enrichment."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_REGISTRY_MESSAGE_BYTES = 16 * 1024 * 1024
_UNSET_REGISTRY = object()


@dataclass(frozen=True, slots=True)
class AreaRegistryEntry:
    """One Home Assistant area registry entry."""

    area_id: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeviceRegistryEntry:
    """One Home Assistant device registry entry."""

    device_id: str
    name: str
    area_id: str | None = None
    via_device_id: str | None = None


@dataclass(frozen=True, slots=True)
class EntityRegistryEntry:
    """One Home Assistant entity registry entry."""

    entity_id: str
    device_id: str | None = None
    area_id: str | None = None
    name: str | None = None
    aliases: tuple[str, ...] = ()
    disabled: bool = False


@dataclass(frozen=True, slots=True)
class RegistryPlacement:
    """Resolved Entity -> Device -> Area relationship with provenance."""

    entity_id: str
    device_id: str | None = None
    device_name: str | None = None
    area_id: str | None = None
    area_name: str | None = None
    confidence: float = 0.0
    source: str = "none"


@dataclass(frozen=True, slots=True)
class HomeAssistantRegistrySnapshot:
    """Immutable registry snapshot used by the world model."""

    updated_at: str
    areas: tuple[AreaRegistryEntry, ...] = ()
    devices: tuple[DeviceRegistryEntry, ...] = ()
    entities: tuple[EntityRegistryEntry, ...] = ()
    area_by_id: dict[str, AreaRegistryEntry] = field(init=False, repr=False)
    device_by_id: dict[str, DeviceRegistryEntry] = field(init=False, repr=False)
    entity_by_id: dict[str, EntityRegistryEntry] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Build immutable lookup indexes."""
        object.__setattr__(
            self, "area_by_id", {item.area_id: item for item in self.areas}
        )
        object.__setattr__(
            self,
            "device_by_id",
            {item.device_id: item for item in self.devices},
        )
        object.__setattr__(
            self,
            "entity_by_id",
            {item.entity_id: item for item in self.entities},
        )

    def placement(self, entity_id: str) -> RegistryPlacement:
        """Resolve one entity through the authoritative registries."""
        entity = self.entity_by_id.get(entity_id)
        if entity is None:
            return RegistryPlacement(entity_id=entity_id)
        device = self.device_by_id.get(entity.device_id or "")
        area_id = entity.area_id or (device.area_id if device is not None else None)
        area = self.area_by_id.get(area_id or "")
        if entity.area_id:
            confidence = 0.99
            source = "entity_registry"
        elif device is not None and device.area_id:
            confidence = 0.97
            source = "device_registry"
        else:
            confidence = 0.0
            source = "registry_unassigned"
        return RegistryPlacement(
            entity_id=entity_id,
            device_id=entity.device_id,
            device_name=device.name if device is not None else None,
            area_id=area_id,
            area_name=area.name if area is not None else area_id,
            confidence=confidence,
            source=source,
        )

    def related_entity_ids(self, entity_id: str) -> tuple[str, ...]:
        """Return entities on the same or directly linked registry devices."""
        entity = self.entity_by_id.get(entity_id)
        if entity is None or entity.device_id is None:
            return ()
        related_devices = {entity.device_id}
        device = self.device_by_id.get(entity.device_id)
        if device is not None and device.via_device_id:
            related_devices.add(device.via_device_id)
        related_devices.update(
            item.device_id
            for item in self.devices
            if item.via_device_id == entity.device_id
        )
        return tuple(
            sorted(
                item.entity_id
                for item in self.entities
                if item.entity_id != entity_id
                and item.device_id in related_devices
                and not item.disabled
            )
        )


@dataclass(frozen=True, slots=True)
class RegistryFetchResult:
    """Structured outcome of one registry fetch."""

    snapshot: HomeAssistantRegistrySnapshot | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return whether a fresh snapshot was loaded."""
        return self.snapshot is not None


class RegistryClient(Protocol):
    """Boundary used by the cacheable registry adapter."""

    def fetch(self) -> RegistryFetchResult:
        """Fetch the three Home Assistant registries."""


class HomeAssistantRegistryWebSocketClient:
    """Fetch Home Assistant registries through one authenticated WebSocket."""

    COMMANDS = (
        "config/area_registry/list",
        "config/device_registry/list",
        "config/entity_registry/list",
    )

    def __init__(
        self,
        *,
        base_url: str | None,
        token: str | None,
        timeout: float = 15.0,
        max_message_bytes: int = DEFAULT_REGISTRY_MESSAGE_BYTES,
        connect_fn: Callable[..., Any] | None = None,
    ) -> None:
        """Initialize credentials and the optional test transport."""
        self.base_url = base_url.rstrip("/") if base_url else None
        self.token = token
        self.timeout = max(1.0, timeout)
        self.max_message_bytes = max(1024 * 1024, max_message_bytes)
        self.connect_fn = connect_fn

    @property
    def is_configured(self) -> bool:
        """Return whether registry access can be attempted."""
        return bool(self.base_url and self.token)

    def fetch(self) -> RegistryFetchResult:
        """Fetch registries without leaking transport exceptions."""
        if not self.is_configured:
            return RegistryFetchResult(
                error="Home Assistant registry is not configured."
            )
        try:
            return RegistryFetchResult(snapshot=asyncio.run(self._fetch()))
        except Exception as exc:
            return RegistryFetchResult(error=str(exc))

    async def _fetch(self) -> HomeAssistantRegistrySnapshot:
        assert self.base_url is not None
        connect_fn = self.connect_fn
        if connect_fn is None:
            from websockets.asyncio.client import connect as connect_fn

        async with connect_fn(
            self._websocket_url(),
            open_timeout=self.timeout,
            ping_interval=20,
            ping_timeout=20,
            max_size=self.max_message_bytes,
        ) as websocket:
            await self._authenticate(websocket)
            results: dict[str, list[dict[str, Any]]] = {}
            for request_id, command in enumerate(self.COMMANDS, start=1):
                results[command] = await self._request(
                    websocket,
                    request_id,
                    command,
                )
        return parse_registry_snapshot(
            areas=results[self.COMMANDS[0]],
            devices=results[self.COMMANDS[1]],
            entities=results[self.COMMANDS[2]],
        )

    async def _authenticate(self, websocket: Any) -> None:
        greeting = _message(await asyncio.wait_for(websocket.recv(), self.timeout))
        if greeting.get("type") != "auth_required":
            raise RuntimeError("Unexpected Home Assistant registry greeting.")
        await websocket.send(json.dumps({"type": "auth", "access_token": self.token}))
        result = _message(await asyncio.wait_for(websocket.recv(), self.timeout))
        if result.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant registry authentication failed.")

    async def _request(
        self,
        websocket: Any,
        request_id: int,
        command: str,
    ) -> list[dict[str, Any]]:
        await websocket.send(json.dumps({"id": request_id, "type": command}))
        response = _message(await asyncio.wait_for(websocket.recv(), self.timeout))
        if response.get("id") != request_id or not response.get("success", False):
            raise RuntimeError(f"Home Assistant registry command failed: {command}")
        result = response.get("result")
        if not isinstance(result, list):
            raise RuntimeError(f"Unexpected Home Assistant registry result: {command}")
        return [item for item in result if isinstance(item, dict)]

    def _websocket_url(self) -> str:
        assert self.base_url is not None
        if self.base_url == "http://supervisor/core":
            return "ws://supervisor/core/websocket"
        if self.base_url.startswith("https://"):
            return f"wss://{self.base_url.removeprefix('https://')}/api/websocket"
        if self.base_url.startswith("http://"):
            return f"ws://{self.base_url.removeprefix('http://')}/api/websocket"
        return f"ws://{self.base_url}/api/websocket"


class EntityRelationship(BaseModel):
    """Optional explicit semantics not represented by Home Assistant registries."""

    model_config = ConfigDict(extra="forbid")

    located_in: str | None = None
    used_for: list[str] = Field(default_factory=list)
    related_to: list[str] = Field(default_factory=list)


class EntityRelationshipDocument(BaseModel):
    """Versioned relationship configuration."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    entities: dict[str, EntityRelationship] = Field(default_factory=dict)


class HomeAssistantRegistryAdapter:
    """Cache registries and enrich state payloads before entity analysis."""

    def __init__(
        self,
        client: RegistryClient,
        *,
        relationship_path: Path | None = None,
        cache_seconds: float = 300.0,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the adapter with a testable transport and bounded cache."""
        self.client = client
        self.relationship_path = relationship_path
        self.cache_seconds = max(0.0, cache_seconds)
        self.monotonic_fn = monotonic_fn
        self.snapshot: HomeAssistantRegistrySnapshot | None = None
        self.last_refresh_at = 0.0
        self.last_refresh_ok = False
        self.last_error: str | None = None
        self.relationships = EntityRelationshipDocument()
        self.logger = logging.getLogger(__name__)
        self.reload_relationships()

    def reload_relationships(self) -> None:
        """Load optional explicit relationships, preserving the last valid file."""
        if self.relationship_path is None or not self.relationship_path.exists():
            return
        try:
            payload = (
                yaml.safe_load(self.relationship_path.read_text(encoding="utf-8")) or {}
            )
            document = EntityRelationshipDocument.model_validate(payload)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            self.logger.warning("Entity relationships could not be reloaded: %s", exc)
            return
        self.relationships = document

    def refresh(self, *, force: bool = False) -> HomeAssistantRegistrySnapshot | None:
        """Return a fresh or cached registry snapshot."""
        now = self.monotonic_fn()
        if (
            not force
            and self.snapshot is not None
            and now - self.last_refresh_at < self.cache_seconds
        ):
            return self.snapshot
        result = self.client.fetch()
        self.last_refresh_at = now
        if result.ok:
            self.snapshot = result.snapshot
            self.last_refresh_ok = True
            self.last_error = None
            return self.snapshot
        self.last_refresh_ok = False
        self.last_error = result.error or "Registry refresh failed."
        self.logger.warning("Home Assistant registry unavailable: %s", self.last_error)
        return self.snapshot

    def enrich_states(
        self,
        states: list[dict[str, Any]],
        *,
        snapshot: HomeAssistantRegistrySnapshot | None | object = _UNSET_REGISTRY,
    ) -> list[dict[str, Any]]:
        """Add authoritative placement and configured relationships to states."""
        registry = (
            self.refresh()
            if snapshot is _UNSET_REGISTRY
            else (
                snapshot
                if isinstance(snapshot, HomeAssistantRegistrySnapshot)
                else None
            )
        )
        enriched: list[dict[str, Any]] = []
        for state in states:
            entity_id = str(state.get("entity_id", ""))
            attributes = state.get("attributes")
            copied_attributes = dict(attributes) if isinstance(attributes, dict) else {}
            placement = (
                registry.placement(entity_id)
                if registry is not None
                else RegistryPlacement(entity_id=entity_id)
            )
            registry_entity = (
                registry.entity_by_id.get(entity_id) if registry is not None else None
            )
            relationship = self.relationships.entities.get(entity_id)
            related_entity_ids = list(
                registry.related_entity_ids(entity_id) if registry is not None else ()
            )
            if placement.device_id:
                copied_attributes["device_id"] = placement.device_id
            if placement.device_name:
                copied_attributes["device_name"] = placement.device_name
            if placement.area_id:
                copied_attributes["area_id"] = placement.area_id
            if placement.area_name:
                copied_attributes["area_name"] = placement.area_name
            if placement.source != "none":
                copied_attributes["kira_area_source"] = placement.source
                copied_attributes["kira_area_confidence"] = placement.confidence
            if registry_entity is not None:
                if registry_entity.name:
                    copied_attributes["kira_registry_name"] = registry_entity.name
                if registry_entity.aliases:
                    copied_attributes["kira_aliases"] = list(registry_entity.aliases)
            if relationship is not None:
                if relationship.located_in and not placement.area_name:
                    copied_attributes["area_name"] = relationship.located_in
                    copied_attributes["kira_area_source"] = "configuration"
                    copied_attributes["kira_area_confidence"] = 0.9
                if relationship.used_for:
                    copied_attributes["kira_used_for"] = list(relationship.used_for)
                if relationship.related_to:
                    related_entity_ids.extend(relationship.related_to)
            if related_entity_ids:
                copied_attributes["kira_related_entities"] = list(
                    dict.fromkeys(related_entity_ids)
                )
            enriched.append({**state, "attributes": copied_attributes})
        return enriched


def parse_registry_snapshot(
    *,
    areas: list[dict[str, Any]],
    devices: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> HomeAssistantRegistrySnapshot:
    """Normalize Home Assistant registry response objects."""
    return HomeAssistantRegistrySnapshot(
        updated_at=datetime.now(UTC).isoformat(),
        areas=tuple(
            AreaRegistryEntry(
                area_id=str(item["area_id"]),
                name=str(item.get("name") or item["area_id"]),
                aliases=_strings(item.get("aliases")),
            )
            for item in areas
            if item.get("area_id")
        ),
        devices=tuple(
            DeviceRegistryEntry(
                device_id=str(item["id"]),
                name=str(
                    item.get("name_by_user") or item.get("name") or item.get("id")
                ),
                area_id=_optional_text(item.get("area_id")),
                via_device_id=_optional_text(item.get("via_device_id")),
            )
            for item in devices
            if item.get("id")
        ),
        entities=tuple(
            EntityRegistryEntry(
                entity_id=str(item["entity_id"]),
                device_id=_optional_text(item.get("device_id")),
                area_id=_optional_text(item.get("area_id")),
                name=_optional_text(item.get("name") or item.get("original_name")),
                aliases=_strings(item.get("aliases")),
                disabled=item.get("disabled_by") is not None,
            )
            for item in entities
            if item.get("entity_id")
        ),
    )


def _message(value: str | bytes) -> dict[str, Any]:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected Home Assistant registry message.")
    return payload


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple | set):
        return ()
    return tuple(str(item) for item in value if item is not None and str(item).strip())


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
