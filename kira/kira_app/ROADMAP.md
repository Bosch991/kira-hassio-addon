# Roadmap

## 1.6.0 Home Status & Daily Briefing

- lokale Hausstatus-Erkennung
- `/ha status`
- `/briefing`
- `/briefing speak`

## 1.5.0 Home Assistant OS Add-on

- Kira laeuft komplett als Home-Assistant-OS-Add-on auf Hassio/NUC
- Server-only Runtime ohne Windows-Desktop-Abhaengigkeit
- interne Home-Assistant-API ueber Supervisor und `SUPERVISOR_TOKEN`
- persistente Daten unter `/data`
- Add-on Optionen fuer OpenAI, ElevenLabs, OpenArt, API Token und media_player
- Paketierung per `scripts/package-hassio-addon.ps1`
- Kira Assist Custom Integration zeigt auf die Add-on-API

## 1.4.0 Windows Desktop App

- PySide6-basierte Desktop-App per `python -m kira desktop`
- Avatarbereich mit Platzhalter und vorbereiteten Emotionsdateien
- Chatverlauf, Texteingabe, Mikrofon-Button und Sprechen-Button
- Statusanzeige fuer OpenAI, Home Assistant, ElevenLabs, Audio und Modell
- System Tray mit Oeffnen, Minimieren und Beenden
- vorbereiteter Windows-Build per `scripts/build-windows.ps1`

## 1.3.0 Home Assistant Safe Control

- Permission-System unter `config/ha_permissions.yaml`
- Auto-Execute fuer sichere Standardaktionen wie Licht, Fan und Lautstaerke
- Confirm/Block-Regeln fuer riskante und sicherheitskritische Aktionen
- Home-Assistant-World-Model fuer strukturierte Sicht auf Entities und Events
- Aktionsprotokoll unter `data/homeassistant/action_log.json`
- Undo-Vorbereitung fuer einfache Licht/Switch/Fan-Aktionen
- raum- und kontextbezogene Assist-Steuerung ueber `area_id` und Metadaten

## 1.2.0 Home Assistant Assist Agent

- FastAPI Server per `python -m kira server`
- `/server start|stop|status` im Chat
- Bearer-Token fuer `POST /chat` und `POST /assist`
- `GET /health`, `GET /version`, `GET /plugins`
- Home Assistant Assist Contract fuer `POST /assist`
- Custom Integration Skeleton `kira_assist`
- Alexa Media Player Erkennung
- `/ha media alexa`
- zielgerichtete Ausgabe mit `/speak ...`

## 1.1.0 OpenArt Kira Model

- OpenArt-Konfiguration fuer bestehendes Kira-Modell, Kira-Style und Kira-World
- `.env`-IDs fuer Model, Style, World und Default-Projekt
- `/openart account`, `/openart projects`, `/openart models`
- `/openart kira info`
- `/openart generate <prompt>`
- Kira-Style-Prompt unter `prompts/openart_kira_style.md`
- lokale Bildausgabe unter `data/openart/`
- lokale History unter `data/openart/history.json`
- OpenArt-Plugin fuer die Plattform-Architektur

## 1.0.0 Platform Release

- Plugin-System mit Manifest, Loader, Manager und Healthchecks
- Core-Plugins fuer Home Assistant, Voice, OpenAI, Memory und Knowledge
- Plugin-Konfiguration unter `config/plugins/`
- Event-Bus fuer interne Plugin-Kommunikation
- Scheduler-Infrastruktur ohne Automationsausfuehrung
- FastAPI-Vorbereitung mit `/`, `/health`, `/plugins`, `/chat`
- Benutzerprofil unter `data/profile.json`
- Desktop-Architekturplatzhalter
- lokale Telemetrie ohne externe Uebertragung
- Backup, Export und Import fuer lokale Kira-Daten
- bisherige Features bleiben erhalten

## 1.4 Plugin API stabilisieren

- Versioniertes Plugin-SDK
- Abhaengigkeitsauflosung mit Startreihenfolge
- Plugin-spezifische Settings-Schemata
- Event-Subscription-Helfer fuer Plugins
- Plugin-Testharness

## 1.5 Scheduler aktivieren

- persistente geplante Aufgaben
- einfache Intervalle und Cron-Ausdruecke
- manuelle Freigabe fuer Home-Assistant-Aktionen
- Scheduler-Events im Event-Bus

## 1.6 API absichern

- lokale Authentifizierung
- API-Tokens
- strukturierte Fehlerantworten
- WebSocket-Stream fuer Events
- OpenAPI-Dokumentation fuer Plugin-Endpunkte

## 1.7 Desktop Shell

- lokale Desktop-App als Shell um Chat, Plugins und Status
- Plugin-Statusansicht
- Backup/Restore-UI
- Profil-Editor

## 1.8 Voice Runtime

- optionaler lokaler TTS-Provider
- besseres Device-Mapping
- Voice-Session-Status im Event-Bus
- Wakeword nur nach expliziter Entscheidung

## 1.9 Home Assistant Aktionen

- sichere Aktionsbestaetigungen
- Bereichs- und Geraetemodelle direkt aus Home Assistant
- Szenensteuerung
- Audit-Log fuer Aktionen

## 1.10 Plugin Marketplace lokal

- lokale Plugin-Registry
- installierbare Plugin-Pakete
- Signatur-/Hash-Pruefung fuer lokale Pakete
- Update-Workflow

## 1.11 Multi-User Profile

- mehrere lokale Profile
- profilabhaengige Modelle, Stimmen und Standardgeraete
- Import/Export einzelner Profile

## 1.12 Automations Workbench

- lokale, pruefbare Kira-Automationen
- Simulation vor Ausfuehrung
- Event-basierte Trigger
- sichere Home-Assistant-Bruecke

## 2.0 Personal OS Layer

- stabile Plattform-API
- stabile Plugin-Kompatibilitaet
- Desktop, API, Voice und Home Assistant als gleichwertige Oberflaechen
- vollstaendige lokale Backup-/Restore-Strategie
- optional verteilbare Runtime fuer mehrere Geraete
