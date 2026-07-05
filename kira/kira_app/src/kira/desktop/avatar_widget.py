"""Avatar widget for the Kira desktop app."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class AvatarWidget(QWidget):
    """Display Kira's avatar or a calm placeholder."""

    def __init__(self, avatar_path: Path) -> None:
        """Initialize the avatar widget."""
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.avatar_path = avatar_path
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setObjectName("avatarLabel")
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        self.set_state("idle")

    def set_state(self, state: str) -> None:
        """Set the avatar state for future animated/emotional variants."""
        path = self._state_path(state)
        if not path.exists():
            self.logger.warning("Avatar image missing: %s", path)
            self._show_placeholder(state)
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.logger.warning("Avatar image could not be loaded: %s", path)
            self._show_placeholder(state)
            return
        self.label.setPixmap(
            pixmap.scaled(
                220,
                220,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _state_path(self, state: str) -> Path:
        if state == "idle":
            idle = self.avatar_path.with_name("kira_idle.png")
            if idle.exists():
                return idle
        if state in {"speaking", "listening", "thinking"}:
            candidate = self.avatar_path.with_name(f"kira_{state}.png")
            if candidate.exists():
                return candidate
        return self.avatar_path

    def _show_placeholder(self, state: str) -> None:
        self.label.setText(f"Kira\n{state}")
        self.label.setMinimumSize(220, 220)
