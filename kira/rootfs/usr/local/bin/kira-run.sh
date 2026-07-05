#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/kira-venv/bin:${PATH}"
export KIRA_ADDON_MODE=true
export KIRA_ROOT_DIR=/opt/kira
export KIRA_DATA_DIR=/data
export KIRA_LOG_DIR=/data/logs
export KIRA_CONFIG_DIR=/data/config
export KIRA_PROMPTS_DIR=/data/prompts
export KIRA_KNOWLEDGE_DIR=/data/knowledge
export KIRA_PLUGINS_DIR=/opt/kira/plugins
export KIRA_PLUGIN_CONFIG_DIR=/data/config/plugins
export KIRA_VOICE_DIR=/data/voice
export KIRA_AUDIO_INPUT_DIR=/data/audio/input
export KIRA_AUDIO_SETTINGS_PATH=/data/audio/settings.json
export KIRA_HA_LIVE_EVENTS_PATH=/data/homeassistant/live_events.json
export KIRA_HA_EVENT_FILTERS_PATH=/data/config/ha_event_filters.yaml
export KIRA_HA_PERMISSIONS_PATH=/data/config/ha_permissions.yaml
export KIRA_HA_ACTION_LOG_PATH=/data/homeassistant/action_log.json
export KIRA_PROFILE_PATH=/data/profile.json
export KIRA_TELEMETRY_PATH=/data/telemetry.json
export KIRA_OPENART_DIR=/data/openart
export KIRA_OPENART_HISTORY_PATH=/data/openart/history.json
export KIRA_API_HOST=0.0.0.0
export KIRA_API_PORT=8787
export KIRA_MEDIA_SERVER_HOST=0.0.0.0
export KIRA_MEDIA_SERVER_PORT=8765
export HOMEASSISTANT_URL=http://supervisor/core

eval "$(/usr/local/bin/kira-options-to-env.py)"

mkdir -p \
  /data/audio \
  /data/config \
  /data/config/plugins \
  /data/homeassistant \
  /data/knowledge \
  /data/logs \
  /data/openart \
  /data/prompts \
  /data/voice

cp -n /opt/kira/config/*.yaml /data/config/ 2>/dev/null || true
cp -n /opt/kira/config/plugins/*.yaml /data/config/plugins/ 2>/dev/null || true
cp -n /opt/kira/prompts/*.md /data/prompts/ 2>/dev/null || true
cp -n /opt/kira/knowledge/*.md /data/knowledge/ 2>/dev/null || true

python3 - <<'PY'
import json
import os
from pathlib import Path

options_path = Path("/data/options.json")
settings_path = Path(os.environ["KIRA_AUDIO_SETTINGS_PATH"])
if options_path.exists() and not settings_path.exists():
    options = json.loads(options_path.read_text(encoding="utf-8"))
    media_player = options.get("default_media_player") or None
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "mode": "ha" if media_player else "local",
                "input_device": None,
                "output_device": None,
                "ha_media_player": media_player,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
PY

if [[ -z "${KIRA_API_TOKEN:-}" ]]; then
  echo "[WARN] KIRA_API_TOKEN ist leer. /chat und /assist werden POST-Anfragen ablehnen."
fi

echo "[INFO] Starte Kira Add-on auf Port ${KIRA_API_PORT}"
exec python3 -m kira server
