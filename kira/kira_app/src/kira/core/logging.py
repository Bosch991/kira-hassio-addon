"""Logging setup for terminal and rotating log files."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from rich.logging import RichHandler

from kira.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure rich console logging and a rotating file handler."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log_file = settings.log_dir / "kira.log" if settings.log_dir else None

    handlers: list[logging.Handler] = [
        RichHandler(
            rich_tracebacks=True,
            show_path=False,
            markup=True,
        )
    ]

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=1_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
        force=True,
    )
