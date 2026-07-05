# Kira

Kira `1.5.0` ist eine lokale, modulare Assistenten-Plattform. Die bisherigen
Funktionen bleiben erhalten: Terminal-Chat, OpenAI-Fallback, Home Assistant,
Voice, Audio-Routing, Memory, Knowledge und Live-Events. Neu ist die
Plattformschicht: Plugins, Event-Bus, Scheduler-Infrastruktur, API,
Benutzerprofil, Desktop-Vorbereitung, lokale Telemetrie und Backup/Import.
Version `1.1.0` ergaenzt OpenArt-Bildgenerierung mit deinem bestehenden
Kira-Modell, Kira-Style und Kira-World.
Version `1.2.0` bereitet Kira als externen Home-Assistant-Assist-Agent vor
und kann Antworten gezielt ueber Home-Assistant-`media_player` ausgeben,
inklusive Alexa Media Player Geraeten.
Version `1.3.0` ergaenzt sichere Home-Assistant-Steuerung mit Permissions,
World Model, Aktionsprotokoll, Undo-Vorbereitung und raumbezogener Assist-
Kontextaufloesung.
Version `1.4.0` ergaenzt eine optionale Windows-Desktop-App mit Avatar, Chat,
Mikrofon, Sprachausgabe, Statusanzeige und System Tray.
Version `1.5.0` bereitet Kira als vollstaendiges Home-Assistant-OS-Add-on vor,
damit Assist, Home-Assistant-Steuerung, Memory, Knowledge und `media_player`-
Ausgabe direkt auf Hassio/NUC laufen koennen.

## Installation

```powershell
cd Kira
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Start

```powershell
python -m kira chat
python -m kira server
python -m kira desktop
```

Die API startet standardmaessig auf `0.0.0.0:8787`.

## Home Assistant OS Add-on

Kira kann komplett als Add-on auf Home Assistant OS laufen. Auf dem
Entwicklungsrechner wird das Add-on paketiert:

```powershell
.\scripts\package-hassio-addon.ps1
```

Danach den Ordner `homeassistant_addons/kira/` nach `/addons/kira/` auf Home
Assistant kopieren und das Add-on `Kira` installieren. Im Add-on-Modus nutzt
Kira die interne Supervisor API und braucht keinen Home-Assistant-Long-Lived-
Token.

Details: `docs/hassio_addon.md`.

## Konfiguration

Kira liest `.env` und lokale Dateien unter `config/`.

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
STT_PROVIDER=openai
STT_MODEL=whisper-1
HOMEASSISTANT_URL=http://homeassistant.local:8123
HOMEASSISTANT_TOKEN=
OPENART_API_KEY=
OPENART_KIRA_MODEL_ID=
OPENART_KIRA_STYLE_ID=
OPENART_KIRA_WORLD_ID=
OPENART_DEFAULT_PROJECT_ID=
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
KIRA_MEDIA_SERVER_HOST=0.0.0.0
KIRA_MEDIA_SERVER_PORT=8765
KIRA_MEDIA_BASE_URL=http://<NUC-IP>:8765
KIRA_LIVE_NOTIFICATIONS=false
KIRA_API_HOST=0.0.0.0
KIRA_API_PORT=8787
KIRA_API_TOKEN=
KIRA_DESKTOP_THEME=dark
KIRA_AVATAR_PATH=assets/avatar/kira.png
KIRA_START_MINIMIZED=false
LOG_LEVEL=INFO
```

Plugin-Konfiguration liegt unter `config/plugins/<plugin>.yaml`.
Home-Assistant-Aktionsrechte liegen unter `config/ha_permissions.yaml`.
Das lokale Aktionsprotokoll liegt unter `data/homeassistant/action_log.json`.

## Plugins

Kira erkennt Plugins automatisch aus `plugins/<name>/`.

Aktuelle Core-Plugins:

- `homeassistant`: REST-Client, Entity-Analyse und Live-Events
- `voice`: ElevenLabs, Audioaufnahme, STT und Audio-Routing
- `openai`: OpenAI Chat und STT Provider
- `openart`: OpenArt-Bildgenerierung mit Kira-Assets
- `memory`: Erinnerungen und Conversation History
- `knowledge`: Markdown-Wissensbasis

Jedes Plugin besitzt `manifest.json`, `plugin.py` und `README.md`.

## Chat-Kommandos

- `/about`, `/help`, `/stats`, `/reload`, `/exit`
- `/memory`, `/projects`, `Merke: ...`
- `/plugins`
- `/plugin info <name>`
- `/plugin enable <name>`
- `/plugin disable <name>`
- `/plugin reload <name>`
- `/plugin reload all`
- `/plugin health`
- `/backup`
- `/export [path]`
- `/import <path>`
- `/openart account`
- `/openart projects`
- `/openart models`
- `/openart kira info`
- `/openart generate <prompt>`
- `/server start`
- `/server stop`
- `/server status`
- `/undo last`
- `/speak <media_player_entity_id> <text>`
- `/speak alexa <text>`
- `/speak tablet <text>`
- `/speak room <raumname> <text>`
- `/listen`, `/voice [local|ha]`
- `/say <text>`, `/speak_last [local|ha]`, `/voices`
- `/audio devices|current`
- `/audio input <name_or_index>`
- `/audio output <name_or_index>`
- `/audio ha <media_player_entity_id>`
- `/audio mode local|ha`
- `/media server start|stop|status`
- `/ha ping|config|states|summary|lights|on|unavailable`
- `/ha media alexa`
- `/ha find <suchtext>`, `/ha room <raumname>`, `/ha export`
- `/ha live start|stop|status|events|clear`
- `/ha entity <entity_id>`
- `/ha service <domain> <service> <entity_id>`

Natuerliche Assist-Schaltbefehle laufen ueber Sicherheitsregeln: harmlose
Licht-, Medienlautstaerke- und Fan-Aktionen duerfen automatisch laufen, riskante
Aktionen benoetigen Bestaetigung, sicherheitskritische Aktionen werden blockiert.

## API

Vorbereitete Endpunkte:

- `GET /`
- `GET /health`
- `GET /version`
- `GET /plugins`
- `POST /chat`
- `POST /assist`

POST-Endpunkte benoetigen `Authorization: Bearer <KIRA_API_TOKEN>`.

## Projektstruktur

```text
Kira/
|-- plugins/
|   |-- homeassistant/
|   |-- knowledge/
|   |-- memory/
|   |-- openai/
|   |-- openart/
|   `-- voice/
|-- config/
|   `-- plugins/
|-- src/kira/
|   |-- api/
|   |-- audio/
|   |-- backup/
|   |-- chat/
|   |-- core/
|   |-- desktop/
|   |-- events/
|   |-- homeassistant/
|   |-- knowledge/
|   |-- memory/
|   |-- openai/
|   |-- openart/
|   |-- plugins/
|   |-- profile/
|   |-- scheduler/
|   |-- telemetry/
|   `-- voice/
|-- docs/
|-- knowledge/
|-- prompts/
`-- tests/
```

## Entwicklung

```powershell
python -m pytest
python -m ruff check .
python -m black --check .
```

Weitere Details:

- `docs/platform.md`
- `docs/plugins.md`
- `docs/events.md`
- `docs/api.md`
- `docs/homeassistant_assist.md`
- `docs/hassio_addon.md`
- `docs/alexa_media.md`
- `docs/openart.md`
- `docs/profile.md`
- `docs/scheduler.md`
