"""System tray integration for Kira desktop."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget


class KiraTray:
    """Small system tray menu."""

    def __init__(
        self,
        window: QWidget,
        *,
        action_handler: Callable[[str], None] | None = None,
        companion_handler: Callable[[], None] | None = None,
    ) -> None:
        """Initialize tray actions."""
        self.window = window
        self.action_handler = action_handler
        self.companion_handler = companion_handler
        self.tray = QSystemTrayIcon(QIcon(), window)
        self.tray.setToolTip("Kira")
        menu = QMenu(window)
        open_action = QAction("Kira oeffnen", window)
        minimize_action = QAction("Minimieren", window)
        quit_action = QAction("Beenden", window)
        open_action.triggered.connect(self.window.showNormal)
        minimize_action.triggered.connect(self.window.hide)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(open_action)
        menu.addAction(minimize_action)
        companion_action = QAction("Companion anzeigen / ausblenden", window)
        companion_action.triggered.connect(self._toggle_companion)
        menu.addAction(companion_action)
        menu.addSeparator()
        for label, action in (
            ("Hausstatus", "home_status"),
            ("Briefing", "briefing"),
            ("Briefing sprechen", "briefing_speak"),
            ("Healthcheck", "healthcheck"),
            ("Updates pruefen", "updates_check"),
            ("Server starten", "server_start"),
            ("Server stoppen", "server_stop"),
            ("Neustart-Hinweis", "restart_hint"),
        ):
            tray_action = QAction(label, window)
            tray_action.triggered.connect(
                lambda checked=False, action_name=action: self._run_action(action_name)
            )
            menu.addAction(tray_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)

    def show(self) -> None:
        """Show the tray icon if supported."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _run_action(self, action: str) -> None:
        if self.action_handler is not None:
            self.window.showNormal()
            self.action_handler(action)

    def _toggle_companion(self) -> None:
        if self.companion_handler is not None:
            self.companion_handler()
