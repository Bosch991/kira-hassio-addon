"""Command line interface for Kira."""

from __future__ import annotations

import argparse
import logging

from kira.chat.session import ChatSession
from kira.core.app import create_app
from kira.version import KIRA_VERSION


def build_parser() -> argparse.ArgumentParser:
    """Build the Kira command line parser."""
    parser = argparse.ArgumentParser(prog="kira", description="Kira local assistant")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("chat", help="Start the local terminal chat")
    subparsers.add_parser("api", help="Start the local Kira API server")
    subparsers.add_parser("server", help="Start the local Kira API server")
    subparsers.add_parser("desktop", help="Start the Kira desktop app")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the command line interface."""
    parser = build_parser()
    parser.add_argument("--version", action="store_true", help="Show Kira version")
    args = parser.parse_args(argv)

    if args.version:
        print(KIRA_VERSION)
        return

    app = create_app()
    app.start()

    if args.command == "chat":
        ChatSession.from_app(app).run()
        return

    if args.command in {"api", "server"}:
        import uvicorn

        from kira.api.server import create_api

        uvicorn.run(
            create_api(app),
            host=app.settings.api_host,
            port=app.settings.api_port,
        )
        return

    if args.command == "desktop":
        from kira.desktop.app import run_desktop_app

        raise SystemExit(run_desktop_app(app))

    logger = logging.getLogger(__name__)
    logger.info("Kira started successfully.")
    logger.info("Memory store: %s", app.memory.path)
