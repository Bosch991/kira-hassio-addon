"""Main window for the Kira desktop app."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStatusBar, QVBoxLayout, QWidget

from kira.chat.session import ChatSession
from kira.desktop.avatar_widget import AvatarWidget
from kira.desktop.chat_widget import ChatWidget
from kira.desktop.companion import (
    CompanionActionController,
    CompanionMood,
    CompanionSettingsStore,
    CompanionWindow,
)
from kira.desktop.dashboard import DesktopCommandResult, DesktopDashboardController
from kira.desktop.status_widget import (
    DashboardWidget,
    DesktopStatusViewModel,
    QuickActionsWidget,
    StatusWidget,
)
from kira.desktop.tray import KiraTray


class DesktopTaskWorker(QObject):
    """Run one desktop task away from the UI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, work: Callable[[], object]) -> None:
        """Initialize worker with a callable task."""
        super().__init__()
        self.work = work

    def run(self) -> None:
        """Execute the task and emit a Qt signal."""
        try:
            self.finished.emit(self.work())
        except Exception as exc:  # pragma: no cover - defensive Qt boundary
            self.failed.emit(str(exc))


class KiraMainWindow(QMainWindow):
    """Kira desktop shell."""

    def __init__(self, app: Any) -> None:
        """Initialize the main window."""
        super().__init__()
        self.kira_app = app
        self.session = ChatSession.from_app(app)
        self.dashboard_controller = DesktopDashboardController(app, self.session)
        self.companion_action_controller = CompanionActionController(
            self.dashboard_controller
        )
        self.status_model = DesktopStatusViewModel()
        self.last_response = ""
        self.workers: dict[QThread, DesktopTaskWorker] = {}
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
        self.dashboard = DashboardWidget(self.dashboard_controller.snapshot())
        self.quick_actions = QuickActionsWidget()
        self.status_widget.media_player_selected.connect(self._set_media_player)
        self.quick_actions.action_requested.connect(self._run_quick_action)
        self.companion_settings_store = CompanionSettingsStore(
            app.settings.companion_settings_path
        )
        self.companion = self._create_companion()
        self.tray = KiraTray(
            self,
            action_handler=self._run_quick_action,
            companion_handler=self._toggle_companion,
        )

        side = QVBoxLayout()
        side.addWidget(self.avatar)
        side.addWidget(self.dashboard)
        side.addWidget(self.quick_actions)
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
        if self.companion.settings.show_on_start:
            self.companion.show()

    def _send_message(self, text: str) -> None:
        self.chat.set_busy(True)
        self.avatar.set_state("thinking")
        self.chat.append_user(text)
        self.companion.set_mood(CompanionMood.THINKING)
        self._run_background(
            lambda: self.session.handle_local_input(text),
            self._finish_chat_response,
        )

    def _run_quick_action(self, action: str) -> None:
        if action == "companion_toggle":
            self._toggle_companion()
            return
        if action == "refresh_status":
            self._refresh_status()
            self.chat.append_kira("Status aktualisiert.")
            self.statusBar().showMessage("Status aktualisiert")
            return
        self.chat.set_busy(True)
        self.avatar.set_state("thinking")
        self.companion.set_mood(CompanionMood.THINKING)
        self._run_background(
            lambda: self.dashboard_controller.run_action(action),
            self._finish_quick_action,
        )

    def _finish_chat_response(self, result: object) -> None:
        response = str(result)
        self.last_response = response
        self.chat.append_kira(response)
        self.companion.show_message(response, mood=CompanionMood.HAPPY)
        self.statusBar().showMessage("Antwort empfangen")
        self._finish_background_task()

    def _finish_quick_action(self, result: object) -> None:
        if not isinstance(result, DesktopCommandResult):
            self.chat.append_kira("Desktop-Aktion lieferte keine gueltige Antwort.")
            self._finish_background_task()
            return
        self.chat.append_user(result.user_text)
        self.chat.append_kira(result.response)
        mood = self._mood_for_action_response(result)
        self.companion.show_message(result.response, mood=mood)
        self.last_response = result.response
        self.statusBar().showMessage("Aktion ausgefuehrt")
        self._finish_background_task()

    def _finish_background_task(self) -> None:
        self.avatar.set_state("idle")
        self.companion.set_mood(CompanionMood.IDLE)
        self._refresh_status()
        self.chat.set_busy(False)

    def _run_background(
        self,
        work: Callable[[], object],
        on_success: Callable[[object], None],
    ) -> None:
        thread = QThread(self)
        worker = DesktopTaskWorker(work)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_success)
        worker.finished.connect(thread.quit)
        worker.failed.connect(self._background_failed)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._forget_worker(thread))
        self.workers[thread] = worker
        thread.start()

    def _background_failed(self, message: str) -> None:
        friendly = self.dashboard_controller.friendly_error(RuntimeError(message))
        self.chat.append_kira(friendly)
        self.statusBar().showMessage("Aktion fehlgeschlagen")
        self.companion.show_message(friendly, mood=CompanionMood.WARNING)
        self._finish_background_task()

    def _forget_worker(self, thread: QThread) -> None:
        self.workers.pop(thread, None)

    def _create_companion(self) -> CompanionWindow:
        settings = self.companion_settings_store.load()
        settings.show_on_start = self.kira_app.settings.companion_show_on_start
        settings.always_on_top = self.kira_app.settings.companion_always_on_top
        settings.bubble_auto_hide = self.kira_app.settings.companion_bubble_auto_hide
        settings.size = self.kira_app.settings.companion_size
        companion = CompanionWindow(
            action_controller=self.companion_action_controller,
            settings=settings,
            settings_store=self.companion_settings_store,
            avatar_path=self._avatar_path(),
        )
        companion.action_requested.connect(self._run_quick_action)
        companion.open_requested.connect(self._show_main_window)
        companion.details_requested.connect(self._show_last_companion_details)
        return companion

    def _toggle_companion(self) -> None:
        if self.companion.isVisible():
            self.companion.hide()
            self.statusBar().showMessage("Companion ausgeblendet")
        else:
            self.companion.show()
            self.companion.raise_()
            self.statusBar().showMessage("Companion angezeigt")

    def _show_main_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_last_companion_details(self) -> None:
        self._show_main_window()
        if self.last_response:
            self.chat.append_kira(self.last_response)

    def _mood_for_action_response(
        self,
        result: DesktopCommandResult,
    ) -> CompanionMood:
        text = result.response.lower()
        if "fehler" in text or "nicht erreichbar" in text:
            return CompanionMood.WARNING
        user_text = result.user_text.lower()
        if "sprechen" in user_text or "speak" in user_text:
            return CompanionMood.SPEAKING
        return CompanionMood.HAPPY

    def _refresh_status(self) -> None:
        self.dashboard.update_snapshot(self.dashboard_controller.snapshot())
        self.status_widget.update_status(self.status_model.from_app(self.kira_app))
        self.status_widget.update_media_players(
            self.status_model.media_players_from_app(self.kira_app),
            self.status_model.from_app(self.kira_app).media_player,
        )

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
        self._refresh_status()

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
                font-weight: 600;
            }
            QLabel#statusDetail {
                color: #9fb5c0;
                font-size: 12px;
            }
            QGroupBox {
                border: 1px solid #1e3a46;
                border-radius: 8px;
                margin-top: 8px;
                padding: 8px;
            }
            QGroupBox::title {
                color: #d9e7ef;
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QGroupBox[level="ok"] {
                border-color: #1f8a5b;
            }
            QGroupBox[level="warning"] {
                border-color: #9a7a20;
            }
            QGroupBox[level="error"] {
                border-color: #a83f3f;
            }
            """
        )
