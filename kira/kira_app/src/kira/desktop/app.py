"""Desktop app entry point."""

from __future__ import annotations

import logging
import sys
from typing import Any


def run_desktop_app(kira_app: Any) -> int:
    """Run the PySide6 desktop application."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        logging.getLogger(__name__).error(
            "PySide6 is not installed. Install it with: python -m pip install PySide6"
        )
        print("PySide6 fehlt. Installiere es mit: python -m pip install PySide6")
        return 1

    from kira.desktop.main_window import KiraMainWindow

    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setApplicationName("Kira")
    window = KiraMainWindow(kira_app)
    if kira_app.settings.start_minimized:
        window.hide()
    else:
        window.show()
    return int(qt_app.exec())
