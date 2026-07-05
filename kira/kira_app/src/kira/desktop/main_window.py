"""Main window for the Kira desktop app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStatusBar, QVBoxLayout, QWidget

from kira.chat.session import ChatSession
from kira.desktop.avatar_widget import AvatarWidget
from kira.desktop.chat_widget import ChatWidget
from kira.desktop.status_widget import DesktopStatusViewModel, StatusWidget
from kira.desktop.tray import KiraTray


class KiraMainWindow(QMainWindow):
    """Kira desktop shell."""

    def __init__(self, app: Any) -> None:
        """Initialize the main window."""
        super().__init__()
        self.kira_app = app
        self.session = ChatSession.from_app(app)
        self.status_model = DesktopStatusViewModel()
        self.last_response = ""
        self.setWindowTitle("Kira")
        self.resize(1120, 720)
        self._apply_theme()

        avatar_path = self._avatar_path()
        self.avatar = AvatarWidget(avatar_path)
        self.chat = ChatWidget()
        self.status_widget = StatusWidget(
            self.status_model.from_app(app),
            self.status_model.media_players_from_app(app),
        )
        self.status_widget.media_player_selected.connect(self._set_media_player)
        self.tray = KiraTray(self)

        side = QVBoxLayout()
        side.addWidget(self.avatar)
        side.addWidget(self.status_widget)
        side.addStretch(1)

        root = QHBoxLayout()
        root.addLayout(side, 0)
        root.addWidget(self.chat, 1)

        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Kira bereit")
        self.chat.connect_handlers(
            on_send=self._send_message,
            on_microphone=self._microphone_once,
            on_speak=self._speak_last,
        )
        self.tray.show()

    def _send_message(self, text: str) -> None:
        self.chat.set_busy(True)
        self.avatar.set_state("thinking")
        self.chat.append_user(text)
        try:
            response = self.session.handle_assist_message(text)
            self.last_response = response
            self.chat.append_kira(response)
            self.statusBar().showMessage("Antwort empfangen")
        finally:
            self.avatar.set_state("idle")
            self.status_widget.update_status(self.status_model.from_app(self.kira_app))
            self.chat.set_busy(False)

    def _microphone_once(self) -> None:
        self.chat.set_busy(True)
        self.avatar.set_state("listening")
        self.statusBar().showMessage("Aufnahme laeuft")
        try:
            recording = self.session.audio_recorder.record()
            if not recording.ok or recording.path is None:
                self.chat.append_kira(self.session._recording_error_message(recording))
                return
            transcription = self.session.speech_to_text.transcribe(recording.path)
            if not transcription.ok:
                self.chat.append_kira(self.session._stt_error_message(transcription))
                return
            if not transcription.text:
                self.chat.append_kira("Ich konnte keine Sprache erkennen.")
                return
            self._send_message(transcription.text)
        finally:
            self.avatar.set_state("idle")
            self.chat.set_busy(False)

    def _speak_last(self) -> None:
        if not self.last_response:
            self.chat.append_kira("Ich habe noch keine Antwort zum Sprechen.")
            return
        self.avatar.set_state("speaking")
        try:
            ok = self.session._speak_text(self.last_response)
            message = "Sprachausgabe gestartet" if ok else "Keine Ausgabe"
            self.statusBar().showMessage(message)
        finally:
            self.avatar.set_state("idle")

    def _set_media_player(self, entity_id: str) -> None:
        if entity_id:
            self.kira_app.audio_device_manager.set_ha_media_player(entity_id)
            self.statusBar().showMessage(f"media_player gesetzt: {entity_id}")
        else:
            settings = self.kira_app.audio_device_manager.load_settings()
            settings.ha_media_player = None
            self.kira_app.audio_device_manager.save_settings(settings)
            self.statusBar().showMessage("media_player entfernt")
        self.status_widget.update_status(self.status_model.from_app(self.kira_app))

    def _avatar_path(self) -> Path:
        path = self.kira_app.settings.avatar_path
        if path.is_absolute():
            return path
        return self.kira_app.settings.root_dir / path

    def _apply_theme(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #0d1117;
                color: #d9e7ef;
                font-size: 14px;
            }
            QTextEdit, QLineEdit {
                background: #111820;
                border: 1px solid #1e3a46;
                border-radius: 6px;
                padding: 8px;
                color: #e6f6ff;
            }
            QComboBox {
                background: #111820;
                border: 1px solid #1e3a46;
                border-radius: 6px;
                padding: 6px;
                color: #e6f6ff;
            }
            QPushButton {
                background: #06384a;
                border: 1px solid #00a6d6;
                border-radius: 6px;
                padding: 8px 12px;
                color: #dff8ff;
            }
            QPushButton:hover {
                background: #07506a;
            }
            QLabel#avatarLabel {
                border: 1px solid #1e3a46;
                border-radius: 8px;
                color: #6ee7ff;
                font-size: 24px;
                font-weight: 600;
            }
            QLabel#statusValue {
                color: #6ee7ff;
            }
            """
        )
