"""Floating desktop companion for Kira."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from kira.desktop.dashboard import DesktopCommandResult, DesktopDashboardController


class CompanionMood(StrEnum):
    """Supported visual companion states."""

    IDLE = "idle"
    THINKING = "thinking"
    SPEAKING = "speaking"
    WARNING = "warning"
    HAPPY = "happy"


@dataclass(frozen=True, slots=True)
class CompanionAction:
    """One action exposed by the floating companion."""

    key: str
    label: str
    command: str | None = None


@dataclass(slots=True)
class CompanionSettings:
    """Persisted companion display settings."""

    show_on_start: bool = True
    always_on_top: bool = True
    bubble_auto_hide: bool = True
    size: str = "small"
    x: int | None = None
    y: int | None = None


class CompanionSettingsStore:
    """Load and save companion settings locally."""

    def __init__(self, path: Path) -> None:
        """Initialize the store path."""
        self.path = path

    def load(self) -> CompanionSettings:
        """Load settings or return safe defaults."""
        if not self.path.exists():
            return CompanionSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return CompanionSettings()
        return CompanionSettings(
            show_on_start=bool(data.get("show_on_start", True)),
            always_on_top=bool(data.get("always_on_top", True)),
            bubble_auto_hide=bool(data.get("bubble_auto_hide", True)),
            size=str(data.get("size", "small")),
            x=self._optional_int(data.get("x")),
            y=self._optional_int(data.get("y")),
        )

    def save(self, settings: CompanionSettings) -> None:
        """Persist settings locally."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(settings), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def save_position(self, x: int, y: int) -> None:
        """Persist only the latest window position."""
        settings = self.load()
        settings.x = x
        settings.y = y
        self.save(settings)

    def _optional_int(self, value: object) -> int | None:
        if isinstance(value, int):
            return value
        return None


class CompanionActionController:
    """Route companion actions to existing Kira desktop commands."""

    ACTIONS: tuple[CompanionAction, ...] = (
        CompanionAction("home_status", "HA", "/ha status"),
        CompanionAction("briefing", "Briefing", "/briefing"),
        CompanionAction("briefing_speak", "Say", "/briefing speak"),
        CompanionAction("updates_status", "Update", "/updates status"),
        CompanionAction("updates_check", "Update-Check", "/updates check"),
    )

    def __init__(self, dashboard: DesktopDashboardController) -> None:
        """Initialize routing against the dashboard controller."""
        self.dashboard = dashboard

    def actions(self) -> list[CompanionAction]:
        """Return available companion actions."""
        return list(self.ACTIONS)

    def run(self, action: str) -> DesktopCommandResult:
        """Execute one companion action."""
        known = {item.key for item in self.ACTIONS}
        if action in known:
            return self.dashboard.run_action(action)
        if action == "open_desktop":
            return DesktopCommandResult("Desktop oeffnen", "Desktop wird geoeffnet.")
        if action == "hide_companion":
            return DesktopCommandResult(
                "Companion ausblenden",
                "Companion wurde ausgeblendet. Du findest ihn im Tray wieder.",
            )
        return DesktopCommandResult(action, "Unbekannte Companion-Aktion.")

    def command_for(self, action: str) -> str | None:
        """Return the chat command for one companion action."""
        for item in self.ACTIONS:
            if item.key == action:
                return item.command
        return None


class CompanionWindow(QWidget):
    """Small always-on-top floating helper window."""

    action_requested = Signal(str)
    open_requested = Signal()
    details_requested = Signal()
    hidden_requested = Signal()

    def __init__(
        self,
        *,
        action_controller: CompanionActionController,
        settings: CompanionSettings,
        settings_store: CompanionSettingsStore,
        avatar_path: Path,
    ) -> None:
        """Initialize the floating companion widget."""
        super().__init__()
        self.action_controller = action_controller
        self.settings = settings
        self.settings_store = settings_store
        self.avatar_path = avatar_path
        self.drag_position: QPoint | None = None
        self.mood = CompanionMood.IDLE
        self.last_message = "Kira ist bereit."
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._hide_bubble)

        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("companionWindow")
        self._build_ui()
        self._apply_theme()
        self._restore_position()

    def set_mood(self, mood: CompanionMood | str) -> None:
        """Update visual mood state."""
        self.mood = CompanionMood(str(mood))
        self.avatar.setProperty("mood", self.mood.value)
        self.avatar.style().unpolish(self.avatar)
        self.avatar.style().polish(self.avatar)

    def show_message(
        self,
        message: str,
        *,
        mood: CompanionMood = CompanionMood.IDLE,
    ) -> None:
        """Show a short readable bubble message."""
        self.last_message = self._shorten(message)
        self.bubble.setText(self.last_message)
        self.bubble.show()
        self.set_mood(mood)
        if self.settings.bubble_auto_hide:
            self.hide_timer.start(9000)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Start dragging or open desktop on left click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            self.open_requested.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Move the companion while dragging."""
        if self.drag_position is None:
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Persist position after dragging."""
        self.drag_position = None
        self.settings_store.save_position(self.x(), self.y())
        event.accept()

    def _build_ui(self) -> None:
        self.avatar = QLabel()
        self.avatar.setObjectName("companionAvatar")
        self.avatar.setFixedSize(86, 86)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_avatar()

        self.bubble = QLabel(self.last_message)
        self.bubble.setObjectName("companionBubble")
        self.bubble.setWordWrap(True)
        self.bubble.setMaximumWidth(220)
        self.bubble.mousePressEvent = self._bubble_clicked  # type: ignore[method-assign]

        button_row = QHBoxLayout()
        for action in self.action_controller.actions()[:4]:
            button = QPushButton(action.label)
            button.setObjectName("companionButton")
            button.clicked.connect(
                lambda checked=False, action_key=action.key: self.action_requested.emit(
                    action_key
                )
            )
            button_row.addWidget(button)

        panel = QFrame()
        panel.setObjectName("companionPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.addWidget(self.bubble)
        panel_layout.addLayout(button_row)

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(self.avatar)
        root.addWidget(panel)

    def _load_avatar(self) -> None:
        if self.avatar_path.exists():
            pixmap = QPixmap(str(self.avatar_path))
            if not pixmap.isNull():
                self.avatar.setPixmap(
                    pixmap.scaled(
                        82,
                        82,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        self.avatar.setText("Kira")

    def _show_context_menu(self, point: QPoint) -> None:
        menu = QMenu(self)
        for label, action in (
            ("Hausstatus", "home_status"),
            ("Briefing", "briefing"),
            ("Briefing sprechen", "briefing_speak"),
            ("Updates pruefen", "updates_check"),
            ("Desktop oeffnen", "open_desktop"),
            ("Companion ausblenden", "hide_companion"),
        ):
            menu_action = QAction(label, self)
            menu_action.triggered.connect(
                lambda checked=False, action_key=action: self._context_action(
                    action_key
                )
            )
            menu.addAction(menu_action)
        menu.addSeparator()
        quit_action = QAction("Beenden", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)
        menu.exec(point)

    def _context_action(self, action: str) -> None:
        if action == "open_desktop":
            self.open_requested.emit()
            return
        if action == "hide_companion":
            self.hidden_requested.emit()
            self.hide()
            return
        self.action_requested.emit(action)

    def _restore_position(self) -> None:
        if self.settings.x is not None and self.settings.y is not None:
            self.move(self.settings.x, self.settings.y)
        else:
            self.move(80, 120)

    def _bubble_clicked(self, event: QMouseEvent) -> None:
        self.details_requested.emit()
        event.accept()

    def _hide_bubble(self) -> None:
        self.bubble.hide()

    def _shorten(self, message: str) -> str:
        text = " ".join(message.split())
        if len(text) <= 120:
            return text
        return f"{text[:117]}..."

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QLabel#companionAvatar {
                background: rgba(12, 25, 34, 220);
                border: 2px solid #6ee7ff;
                border-radius: 43px;
                color: #dff8ff;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#companionAvatar[mood="thinking"] {
                border-color: #f0c85a;
            }
            QLabel#companionAvatar[mood="speaking"],
            QLabel#companionAvatar[mood="happy"] {
                border-color: #7ee787;
            }
            QLabel#companionAvatar[mood="warning"] {
                border-color: #ff7b72;
            }
            QFrame#companionPanel {
                background: rgba(13, 17, 23, 224);
                border: 1px solid rgba(110, 231, 255, 160);
                border-radius: 10px;
            }
            QLabel#companionBubble {
                color: #e6f6ff;
                padding: 8px;
            }
            QPushButton#companionButton {
                background: rgba(6, 56, 74, 230);
                border: 1px solid #00a6d6;
                border-radius: 6px;
                color: #dff8ff;
                padding: 5px 8px;
                font-size: 12px;
            }
            QPushButton#companionButton:hover {
                background: rgba(7, 80, 106, 240);
            }
            """
        )
