#!/usr/bin/env python3
"""Preflight checks for the Kira Home Assistant add-on."""

from __future__ import annotations

import os
import sys
from pathlib import Path

CRITICAL_PATHS = (
    "KIRA_DATA_DIR",
    "KIRA_LOG_DIR",
    "KIRA_CONFIG_DIR",
    "KIRA_VOICE_DIR",
)


def print_line(level: str, message: str) -> None:
    """Print one structured preflight line."""
    print(f"[{level}] {message}")


def check_writable_path(env_name: str) -> bool:
    """Check whether an environment path is writable."""
    raw_path = os.environ.get(env_name)
    if not raw_path:
        print_line("ERROR", f"{env_name} ist nicht gesetzt.")
        return False

    path = Path(raw_path)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".kira-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        print_line("ERROR", f"{env_name}={path} ist nicht beschreibbar: {exc}")
        return False

    print_line("INFO", f"{env_name}={path} ist beschreibbar.")
    return True


def main() -> int:
    """Run add-on preflight checks."""
    ok = True

    if os.environ.get("KIRA_ADDON_MODE", "").lower() != "true":
        print_line("WARN", "KIRA_ADDON_MODE ist nicht true.")

    if not os.environ.get("SUPERVISOR_TOKEN"):
        print_line(
            "ERROR", "SUPERVISOR_TOKEN fehlt; Home-Assistant-API ist nicht nutzbar."
        )
        ok = False
    else:
        print_line("INFO", "Supervisor-Token ist gesetzt.")

    if not os.environ.get("KIRA_API_TOKEN"):
        print_line(
            "WARN",
            "KIRA_API_TOKEN fehlt; externe POSTs werden abgelehnt.",
        )

    if not os.environ.get("KIRA_MEDIA_BASE_URL"):
        print_line(
            "WARN",
            "KIRA_MEDIA_BASE_URL fehlt; media_player kann MP3s ggf. nicht laden.",
        )

    for env_name in CRITICAL_PATHS:
        ok = check_writable_path(env_name) and ok

    if ok:
        print_line("INFO", "Kira Add-on Preflight erfolgreich.")
        return 0

    print_line("ERROR", "Kira Add-on Preflight fehlgeschlagen.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
