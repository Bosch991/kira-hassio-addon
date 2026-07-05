"""Status widget and view model for Kira desktop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QWidget

from kira.homeassistant.media_players import MediaPlayerMatcher

KIRA_DESKTOP_VERSION = "1.5.0"


@dataclass(frozen=True, slots=True)
class DesktopStatus:
    """Status values shown by the desktop UI."""

    openai: str
    homeassistant: str
    elevenlabs: str
    audio_mode: str
    media_player: str
    model: str
    version: str = KIRA_DESKTOP_VERSION


@dataclass(frozen=True, slots=True)
class DesktopMediaPlayerOption:
    """Selectable media player target for the desktop UI."""

    entity_id: str
    label: str


class DesktopStatusViewModel:
    """Build desktop status values from the Kira application."""

    def __init__(self) -> None:
        """Initialize the view model."""
        self.media_player_matcher = MediaPlayerMatcher()

    def from_app(self, app: Any) -> DesktopStatus:
        """Return display-ready status data."""
        audio_settings = app.audio_device_manager.load_settings()
        return DesktopStatus(
            openai="online" if app.settings.openai_api_key else "offline",
            homeassistant="online" if app.homeassistant.is_configured else "offline",
            elevenlabs="online" if app.voice.is_configured else "offline",
            audio_mode=audio_settings.mode,
            media_player=audio_settings.ha_media_player or "-",
            model=app.settings.openai_model,
        )

    def media_players_from_app(self, app: Any) -> list[DesktopMediaPlayerOption]:
        """Return selectable Home Assistant media players."""
        result = app.homeassistant.states()
        if not result.ok or not isinstance(result.data, list):
            return []
        states = [item for item in result.data if isinstance(item, dict)]
        players = self.media_player_matcher.from_states(states)
        return [
            DesktopMediaPlayerOption(
                entity_id=player.entity_id,
                label=f"{player.name} ({player.entity_id})",
            )
            for player in players
        ]


class StatusWidget(QWidget):
    """Display important runtime status values."""

    media_player_selected = Signal(str)

    def __init__(
        self,
        status: DesktopStatus,
        media_players: list[DesktopMediaPlayerOption] | None = None,
    ) -> None:
        """Initialize the status widget."""
        super().__init__()
        self.labels: dict[str, QLabel] = {}
        self.media_player_combo = QComboBox()
        self.media_player_combo.setObjectName("mediaPlayerCombo")
        layout = QGridLayout(self)
        for row, field_name in enumerate(DesktopStatus.__dataclass_fields__):
            title = QLabel(f"{field_name}:")
            if field_name == "media_player":
                layout.addWidget(title, row, 0)
                layout.addWidget(self.media_player_combo, row, 1)
                continue
            value = QLabel(str(getattr(status, field_name)))
            value.setObjectName("statusValue")
            self.labels[field_name] = value
            layout.addWidget(title, row, 0)
            layout.addWidget(value, row, 1)
        self.update_media_players(media_players or [], status.media_player)
        self.media_player_combo.currentIndexChanged.connect(
            self._emit_selected_media_player
        )

    def update_status(self, status: DesktopStatus) -> None:
        """Update visible status values."""
        for field_name, label in self.labels.items():
            label.setText(getattr(status, field_name))
        self.media_player_combo.blockSignals(True)
        self._select_media_player(status.media_player)
        self.media_player_combo.blockSignals(False)

    def update_media_players(
        self,
        media_players: list[DesktopMediaPlayerOption],
        selected_entity_id: str | None,
    ) -> None:
        """Replace media player dropdown entries."""
        self.media_player_combo.blockSignals(True)
        self.media_player_combo.clear()
        self.media_player_combo.addItem("Kein media_player", "")
        for player in media_players:
            self.media_player_combo.addItem(player.label, player.entity_id)
        self._select_media_player(selected_entity_id or "-")
        self.media_player_combo.blockSignals(False)

    def _select_media_player(self, entity_id: str) -> None:
        target = "" if entity_id == "-" else entity_id
        index = self.media_player_combo.findData(target)
        self.media_player_combo.setCurrentIndex(max(index, 0))

    def _emit_selected_media_player(self) -> None:
        entity_id = self.media_player_combo.currentData()
        if isinstance(entity_id, str):
            self.media_player_selected.emit(entity_id)
