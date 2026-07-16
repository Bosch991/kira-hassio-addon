"""Chat widget for the Kira desktop app."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ChatWidget(QWidget):
    """Chat history and input controls."""

    send_requested = Signal(str)
    microphone_requested = Signal()
    speak_requested = Signal()

    def __init__(self) -> None:
        """Initialize chat controls."""
        super().__init__()
        self.history = QTextEdit()
        self.history.setReadOnly(True)
        self.history.setObjectName("chatHistory")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Nachricht an Kira")
        self.send_button = QPushButton("Senden")
        self.microphone_button = QPushButton("Mikrofon")
        self.speak_button = QPushButton("Sprechen")

        input_row = QHBoxLayout()
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.microphone_button)
        input_row.addWidget(self.speak_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.history, 1)
        layout.addLayout(input_row)

        self.send_button.clicked.connect(self._send_current)
        self.input.returnPressed.connect(self._send_current)
        self.microphone_button.clicked.connect(self.microphone_requested.emit)
        self.speak_button.clicked.connect(self.speak_requested.emit)

    def append_user(self, text: str) -> None:
        """Append a user message."""
        self._append("Du", text)

    def append_kira(self, text: str) -> None:
        """Append a Kira message."""
        self._append("Kira", text)

    def set_busy(self, busy: bool) -> None:
        """Enable or disable controls while work runs."""
        for widget in (
            self.input,
            self.send_button,
            self.microphone_button,
            self.speak_button,
        ):
            widget.setEnabled(not busy)

    def connect_handlers(
        self,
        *,
        on_send: Callable[[str], None],
        on_microphone: Callable[[], None],
        on_speak: Callable[[], None],
    ) -> None:
        """Connect external handlers."""
        self.send_requested.connect(on_send)
        self.microphone_requested.connect(on_microphone)
        self.speak_requested.connect(on_speak)

    def _send_current(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.send_requested.emit(text)

    def _append(self, speaker: str, text: str) -> None:
        safe_text = escape(text).replace("\n", "<br>")
        if speaker == "Du":
            self.history.append(
                f"<p><b>Du:</b><br><blockquote>{safe_text}</blockquote></p>"
            )
            return
        self.history.append(f"<p><b>Kira:</b><br>{safe_text}</p>")
