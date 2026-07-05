"""Route generated speech to local or Home Assistant playback."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from kira.audio.devices import AudioDeviceManager, AudioSettings
from kira.audio.media_server import MediaServer
from kira.audio.player import AudioPlayer
from kira.homeassistant.client import HomeAssistantClient


class AudioRouteStatus(StrEnum):
    """Possible audio routing outcomes."""

    SUCCESS = "success"
    LOCAL_PLAYBACK_FAILED = "local_playback_failed"
    HA_NOT_CONFIGURED = "ha_not_configured"
    HA_MEDIA_PLAYER_MISSING = "ha_media_player_missing"
    MEDIA_BASE_URL_MISSING = "media_base_url_missing"
    HA_PLAYBACK_FAILED = "ha_playback_failed"


@dataclass(frozen=True, slots=True)
class AudioRouteResult:
    """Result of routing an audio file."""

    status: AudioRouteStatus
    message: str

    @property
    def ok(self) -> bool:
        """Return whether routing succeeded."""
        return self.status is AudioRouteStatus.SUCCESS


class AudioRouter:
    """Route MP3 output to local speakers or a HA media_player."""

    def __init__(
        self,
        *,
        device_manager: AudioDeviceManager,
        player: AudioPlayer,
        homeassistant: HomeAssistantClient,
        media_server: MediaServer,
        media_base_url: str | None,
    ) -> None:
        """Initialize the router."""
        self.device_manager = device_manager
        self.player = player
        self.homeassistant = homeassistant
        self.media_server = media_server
        self.media_base_url = media_base_url.rstrip("/") if media_base_url else None

    def route(
        self,
        path: Path,
        *,
        mode_override: str | None = None,
    ) -> AudioRouteResult:
        """Route an MP3 file using persisted settings or an override."""
        settings = self.device_manager.load_settings()
        mode = mode_override or settings.mode
        if mode == "ha":
            return self._route_homeassistant(path, settings)
        return self._route_local(path, settings)

    def route_to_media_player(
        self,
        path: Path,
        entity_id: str,
    ) -> AudioRouteResult:
        """Route an MP3 file directly to one HA media_player entity."""
        settings = self.device_manager.load_settings()
        settings.ha_media_player = entity_id
        return self._route_homeassistant(path, settings)

    def _route_local(
        self,
        path: Path,
        settings: AudioSettings,
    ) -> AudioRouteResult:
        result = self.player.play(path, output_device=settings.output_device)
        if not result.ok:
            return AudioRouteResult(
                status=AudioRouteStatus.LOCAL_PLAYBACK_FAILED,
                message=result.error or "Local playback failed.",
            )
        return AudioRouteResult(
            status=AudioRouteStatus.SUCCESS,
            message=f"Lokal abgespielt: {path}",
        )

    def _route_homeassistant(
        self,
        path: Path,
        settings: AudioSettings,
    ) -> AudioRouteResult:
        if not self.homeassistant.is_configured:
            return AudioRouteResult(
                status=AudioRouteStatus.HA_NOT_CONFIGURED,
                message="Home Assistant ist nicht konfiguriert.",
            )
        if not settings.ha_media_player:
            return AudioRouteResult(
                status=AudioRouteStatus.HA_MEDIA_PLAYER_MISSING,
                message="Kein Home-Assistant-media_player ausgewaehlt.",
            )
        if not self.media_base_url:
            return AudioRouteResult(
                status=AudioRouteStatus.MEDIA_BASE_URL_MISSING,
                message=(
                    "KIRA_MEDIA_BASE_URL fehlt. Home Assistant kann lokale "
                    "Dateien nicht direkt abspielen."
                ),
            )

        media_url = self.media_server.url_for(path, base_url=self.media_base_url)
        result = self.homeassistant.play_media(
            entity_id=settings.ha_media_player,
            media_content_id=media_url,
            media_content_type="music",
        )
        if not result.ok:
            return AudioRouteResult(
                status=AudioRouteStatus.HA_PLAYBACK_FAILED,
                message=result.error or "Home Assistant media playback failed.",
            )
        return AudioRouteResult(
            status=AudioRouteStatus.SUCCESS,
            message=f"An {settings.ha_media_player} gesendet: {media_url}",
        )
