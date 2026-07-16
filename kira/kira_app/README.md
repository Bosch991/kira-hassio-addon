# Kira

Kira `1.9.0` ist eine lokale, modulare Assistenten-Plattform. Die bisherigen
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
Version `1.6.0` ergaenzt Home Status & Daily Briefing. Hausstatus-Fragen und
Briefings laufen lokal ueber Home Assistant und werden nicht an OpenAI
weitergereicht, wenn die Absicht eindeutig erkannt wird.
Version `1.7.0` ergaenzt Update- und Deployment-Komfort fuer lokale Git-
Checkouts und den Home-Assistant-Add-on-Betrieb.
Version `1.8.0` ergaenzt Desktop-Komfort mit Dashboard, Statuskarten,
Schnellbuttons, Healthcheck-Ansicht, Update-Status und erweitertem Tray-Menue.
Version `1.9.0` ergaenzt einen kleinen Floating Desktop Companion mit
Always-on-top-Fenster, Sprechblase, Kira-Avatar, Kontextmenue und
Schnellaktionen.

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
KIRA_COMPANION_SHOW_ON_START=true
KIRA_COMPANION_ALWAYS_ON_TOP=true
KIRA_COMPANION_BUBBLE_AUTO_HIDE=true
KIRA_COMPANION_SIZE=small
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

## Home Status & Daily Briefing

Der Hausstatus nutzt vorhandene Home-Assistant-Daten lokal ueber den
`HomeStatusService`. OpenAI wird dafuer nicht benoetigt.

```text
/ha status
/briefing
/briefing speak
```

`/briefing` fasst nach Verfuegbarkeit Lichter, Fenster/Tueren, Wetter,
PV/Energie, 3D-Drucker, Waschmaschine, Klingel und Auffaelligkeiten kurz
zusammen. `/briefing speak` gibt denselben Text im Terminal aus und nutzt danach
die vorhandene ElevenLabs-/Audio-Routing-Konfiguration fuer Sprachausgabe.

OpenArt ist fuer Hausstatus und Briefing optional. Ein Healthcheck mit
`openart: ok - missing configuration` blockiert diese Funktionen nicht.

## Updates

Kira kann den lokalen Git-Checkout pruefen und sichere Fast-Forward-Updates
ausfuehren. Der Update-Service fuehrt keine Merge-Commits aus, bricht bei
lokalen Aenderungen ab und gibt nur Neustart-Hinweise aus. Prozesse werden nie
automatisch beendet.

```text
/updates status
/updates check
/updates pull
/updates restart
```

`/updates status` zeigt Version, Branch, Commit und lokale Aenderungen.
`/updates check` vergleicht den Checkout mit dem konfigurierten Upstream.
`/updates pull` fuehrt nur bei sauberem Arbeitsbaum `git pull --ff-only` aus.
`/updates restart` erklaert den sicheren Neustart fuer Terminal, API-Server
und Home-Assistant-Add-on.

## Desktop-Komfort

Der Desktop ist eine Komfortoberflaeche fuer lokale Kira-Funktionen. CLI und
API bleiben unveraendert verfuegbar.

Neu in `1.8.0`:

- Dashboard mit kompakten Statuskarten fuer Kira, Server, Home Assistant,
  OpenAI, Voice, Memory/Knowledge und Updates
- Healthcheck-Ansicht fuer `homeassistant`, `knowledge`, `memory`, `openai`,
  `openart` und `voice`
- Schnellbuttons fuer Hausstatus, Briefing, Briefing sprechen, Updates,
  Healthcheck, Version und Status-Refresh
- erweitertes Tray-Menue mit denselben sicheren Schnellaktionen
- Serversteuerung als sichere Hinweise statt automatischem Prozess-Kill

OpenArt mit `missing configuration` ist im Desktop ein Hinweis, kein
blockierender Fehler. Secrets wie API-Keys oder Home-Assistant-Tokens werden
nicht angezeigt.

## Desktop Companion

Kira `1.9.0` startet in der Desktop-App optional einen kleinen Floating
Assistant. Der Companion ist ein leichtgewichtiges, verschiebbares Fenster mit
transparentem Hintergrund, Always-on-top-Modus, Kira-Avatar, kurzer
Sprechblase und Schnellaktionen.

Direkt am Companion:

- `HA` fuer `/ha status`
- `Briefing` fuer `/briefing`
- `Say` fuer `/briefing speak`
- `Update` fuer `/updates status`

Linksklick auf den Companion holt das Desktop-Hauptfenster nach vorne.
Rechtsklick oeffnet ein Kontextmenue mit Hausstatus, Briefing, Briefing
sprechen, Updates pruefen, Desktop oeffnen, Companion ausblenden und Beenden.
Die Sprechblase zeigt kurze Rueckmeldungen und kann automatisch ausblenden.

Vorbereitete Companion-Zustaende:

- `idle`
- `thinking`
- `speaking`
- `warning`
- `happy`

Wenn `assets/avatar/kira.png` fehlt, nutzt Kira eine saubere Platzhalterfigur.
Die Position wird lokal unter `data/desktop/companion_settings.json`
gespeichert.

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
- `/updates status`
- `/updates check`
- `/updates pull`
- `/updates restart`
- `/ha status`
- `/briefing`
- `/briefing speak`
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
