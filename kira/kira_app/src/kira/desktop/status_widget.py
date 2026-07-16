"""Status widget and view model for Kira desktop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from kira.desktop.dashboard import DashboardSnapshot
from kira.homeassistant.media_players import MediaPlayerMatcher
from kira.version import KIRA_VERSION

KIRA_DESKTOP_VERSION = KIRA_VERSION


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


class DashboardWidget(QWidget):
    """Compact dashboard with status cards and health lines."""

    def __init__(self, snapshot: DashboardSnapshot) -> None:
        """Initialize the dashboard cards."""
        super().__init__()
        self.card_labels: dict[str, QLabel] = {}
        self.health_label = QLabel()
        self.health_label.setObjectName("statusDetail")
        self.checked_label = QLabel()
        self.checked_label.setObjectName("statusDetail")

        self.layout = QGridLayout(self)
        self.update_snapshot(snapshot)

    def update_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Update visible dashboard data."""
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for index, card in enumerate(snapshot.cards):
            box = QGroupBox(card.title)
            box.setProperty("level", card.level)
            box_layout = QVBoxLayout(box)
            status = QLabel(card.status)
            status.setObjectName("statusValue")
            detail = QLabel(card.detail)
            detail.setObjectName("statusDetail")
            detail.setWordWrap(True)
            box_layout.addWidget(status)
            box_layout.addWidget(detail)
            self.layout.addWidget(box, index // 2, index % 2)

        health_text = "\n".join(
            f"{item.name}: {item.status}" + (f" - {item.detail}" if item.detail else "")
            for item in snapshot.health
        )
        self.health_label = QLabel(health_text or "Keine Healthcheck-Daten")
        self.health_label.setObjectName("statusDetail")
        self.health_label.setWordWrap(True)
        health_box = QGroupBox("Healthcheck")
        health_layout = QVBoxLayout(health_box)
        health_layout.addWidget(self.health_label)
        self.layout.addWidget(health_box, 4, 0, 1, 2)

        checked = snapshot.checked_at.astimezone().strftime("%H:%M:%S")
        self.checked_label = QLabel(f"Letzter Check: {checked}")
        self.checked_label.setObjectName("statusDetail")
        self.layout.addWidget(self.checked_label, 5, 0, 1, 2)


class QuickActionsWidget(QWidget):
    """Quick action buttons for common local Kira commands."""

    action_requested = Signal(str)

    ACTIONS: tuple[tuple[str, str], ...] = (
        ("Hausstatus", "home_status"),
        ("Briefing", "briefing"),
        ("Briefing sprechen", "briefing_speak"),
        ("Updates pruefen", "updates_check"),
        ("Update-Status", "updates_status"),
        ("Healthcheck", "healthcheck"),
        ("Version", "version"),
        ("Status aktualisieren", "refresh_status"),
        ("Server starten", "server_start"),
        ("Server stoppen", "server_stop"),
        ("Serverstatus", "server_status"),
    )

    def __init__(self) -> None:
        """Initialize quick action buttons."""
        super().__init__()
        layout = QGridLayout(self)
        for index, (label, action) in enumerate(self.ACTIONS):
            button = QPushButton(label)
            button.clicked.connect(
                lambda checked=False, action_name=action: self.action_requested.emit(
                    action_name
                )
            )
            layout.addWidget(button, index // 2, index % 2)


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
