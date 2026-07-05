"""System tray integration for Kira desktop."""

from __future__ import annotations

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget


class KiraTray:
    """Small system tray menu."""

    def __init__(self, window: QWidget) -> None:
        """Initialize tray actions."""
        self.window = window
        self.tray = QSystemTrayIcon(QIcon(), window)
        self.tray.setToolTip("Kira")
        menu = QMenu(window)
        open_action = QAction("Oeffnen", window)
        minimize_action = QAction("Minimieren", window)
        quit_action = QAction("Beenden", window)
        open_action.triggered.connect(self.window.showNormal)
        minimize_action.triggered.connect(self.window.hide)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(open_action)
        menu.addAction(minimize_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)

    def show(self) -> None:
        """Show the tray icon if supported."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
