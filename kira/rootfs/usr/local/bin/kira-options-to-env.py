#!/usr/bin/env python3
"""Print shell exports for Kira add-on options."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

OPTIONS_PATH = Path("/data/options.json")

OPTION_ENV_MAP = {
    "openai_api_key": "OPENAI_API_KEY",
    "openai_model": "OPENAI_MODEL",
    "kira_api_token": "KIRA_API_TOKEN",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "elevenlabs_voice_id": "ELEVENLABS_VOICE_ID",
    "media_base_url": "KIRA_MEDIA_BASE_URL",
    "openart_api_key": "OPENART_API_KEY",
    "openart_kira_model_id": "OPENART_KIRA_MODEL_ID",
    "openart_kira_style_id": "OPENART_KIRA_STYLE_ID",
    "openart_kira_world_id": "OPENART_KIRA_WORLD_ID",
    "openart_default_project_id": "OPENART_DEFAULT_PROJECT_ID",
    "log_level": "LOG_LEVEL",
    "live_notifications": "KIRA_LIVE_NOTIFICATIONS",
}


def main() -> None:
    """Emit export statements for non-empty configured options."""
    if not OPTIONS_PATH.exists():
        return

    options = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
    if not isinstance(options, dict):
        return

    for option_name, env_name in OPTION_ENV_MAP.items():
        value = options.get(option_name)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"export {env_name}={shlex.quote(str(value))}")


if __name__ == "__main__":
    main()
