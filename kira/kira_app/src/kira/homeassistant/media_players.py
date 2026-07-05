"""Home Assistant media_player discovery and matching helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MediaPlayerView:
    """Compact Home Assistant media_player view."""

    entity_id: str
    name: str
    state: str
    area: str | None = None
    is_alexa: bool = False


ALEXA_MARKERS = ("echo", "alexa", "fire tv", "speaker group")


class MediaPlayerMatcher:
    """Find suitable Home Assistant media_player targets."""

    def from_states(self, states: list[dict[str, Any]]) -> list[MediaPlayerView]:
        """Extract media players from Home Assistant state payloads."""
        players: list[MediaPlayerView] = []
        for item in states:
            entity_id = str(item.get("entity_id", ""))
            if not entity_id.startswith("media_player."):
                continue
            attributes = item.get("attributes", {})
            attributes = attributes if isinstance(attributes, dict) else {}
            name = str(attributes.get("friendly_name") or entity_id)
            area = attributes.get("area") or attributes.get("area_id")
            players.append(
                MediaPlayerView(
                    entity_id=entity_id,
                    name=name,
                    state=str(item.get("state", "unknown")),
                    area=str(area) if area else None,
                    is_alexa=self.is_alexa(entity_id=entity_id, name=name),
                )
            )
        return players

    def is_alexa(self, *, entity_id: str, name: str) -> bool:
        """Return whether a media player looks like an Alexa device."""
        haystack = f"{entity_id} {name}".lower().replace("_", " ")
        return any(marker in haystack for marker in ALEXA_MARKERS)

    def best_match(
        self,
        players: list[MediaPlayerView],
        selector: str,
    ) -> MediaPlayerView | None:
        """Find a media player by entity id, alias, area, or fuzzy name."""
        selector = selector.strip()
        if not selector:
            return None
        lowered = selector.lower()
        if lowered.startswith("media_player."):
            return next((item for item in players if item.entity_id == selector), None)
        if lowered == "alexa":
            return next((item for item in players if item.is_alexa), None)
        if lowered == "tablet":
            return self._contains(players, ("tablet", "tab a9", "tab_a9"))
        return self._contains(players, (lowered,))

    def best_room_match(
        self,
        players: list[MediaPlayerView],
        room: str,
    ) -> MediaPlayerView | None:
        """Find the best media player for a room name."""
        lowered = room.strip().lower()
        if not lowered:
            return None
        area_match = next(
            (
                item
                for item in players
                if item.area is not None and lowered in item.area.lower()
            ),
            None,
        )
        if area_match is not None:
            return area_match
        return self._contains(players, (lowered,))

    def _contains(
        self,
        players: list[MediaPlayerView],
        needles: tuple[str, ...],
    ) -> MediaPlayerView | None:
        for item in players:
            haystack = f"{item.entity_id} {item.name}".lower().replace("_", " ")
            if any(needle in haystack for needle in needles):
                return item
        return None
