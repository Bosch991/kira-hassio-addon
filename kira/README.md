# Kira Home Assistant OS Add-on

Dieses Add-on startet Kira komplett auf Home Assistant OS. Der Windows-Rechner
muss fuer Assist, Home-Assistant-Steuerung, Memory, Knowledge und
`media_player`-Ausgabe nicht mehr laufen.

## Kira 2.1

Natuerliche Anfragen aus Home Assistant Assist laufen ueber Kiras
kontextbewussten Agenten. Kira liest aktuelle States, loest Raum und Geraet
dynamisch auf, bevorzugt vorhandene Scenes/Scripts/Automationen und prueft den
erreichten Zustand nach einer Aktion erneut.

Kira verdichtet den Hauszustand jetzt zu einer semantischen Situation, nutzt
Entity-/Device-/Area-Registry, konfigurierbare Goals und explizite
Praeferenzen. Bedingte Auftraege werden als persistente Tasks gespeichert und
erst nach ihrem Live-Event sowie einer erneuten Safety-Pruefung ausgefuehrt.

## Wichtige Optionen

- `openai_api_key`: erforderlich fuer freie Gespraeche und semantische Intents.
- `agent_semantic_enabled`: OpenAI-Interpretation mit lokalem Fallback.
- `agent_confirmation_seconds`: Ablaufzeit sicherheitsrelevanter Plaene.
- `agent_verification_attempts`: begrenzte State-Pruefungen nach Aktionen.
- `ha_registry_cache_seconds`: Cachezeit fuer HA Registry-Metadaten.
- `proactive_mode`: standardmaessig nur `detect`.
- `proactive_auto_execute`: sicherer Standard ist `false`.
- `kira_api_token`: Token, das die Kira Assist Custom Integration nutzt.
- `default_media_player`: optionales Standard-Ausgabegeraet.
- `media_base_url`: z. B. `http://<HA-IP>:8765`, wenn Kira TTS an
  `media_player` senden soll.

Die Home-Assistant-API wird intern ueber den Supervisor genutzt. Es ist kein
Long-Lived Access Token noetig.

## Stabilitaet

Beim Start prueft Kira:

- Supervisor-Token fuer Home Assistant
- Schreibrechte unter `/data`
- Kira API Token
- Media Base URL fuer `media_player`-Ausgabe

Der Container hat einen Healthcheck auf `/health`. Fuer Details:

- `http://<HA-IP>:8787/health`
- `http://<HA-IP>:8787/addon/status`

`/addon/status` prueft auch `homeassistant_api`. Dieser Check zeigt, ob Kira
ueber den Supervisor wirklich auf Home Assistant Core zugreifen kann.

## Persistenz

Kira speichert Daten unter `/data`:

- Memory und Conversation History
- Knowledge
- Plugin-Konfiguration
- Home-Assistant-Aktionsprotokoll
- Agenten-Kontext und ausstehende Bestaetigungsplaene
- Goals, explizite Praeferenzen und persistente Tasks
- OpenArt-History
- Voice-Dateien

Beim ersten Start werden Standarddateien aus dem Container nach `/data`
kopiert.
