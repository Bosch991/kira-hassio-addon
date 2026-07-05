# Kira Home Assistant OS Add-on

Dieses Add-on startet Kira komplett auf Home Assistant OS. Der Windows-Rechner
muss fuer Assist, Home-Assistant-Steuerung, Memory, Knowledge und
`media_player`-Ausgabe nicht mehr laufen.

## Wichtige Optionen

- `openai_api_key`: erforderlich fuer freie Gesprae.
- `kira_api_token`: Token, das die Kira Assist Custom Integration nutzt.
- `default_media_player`: optionales Standard-Ausgabegeraet.
- `media_base_url`: z. B. `http://<HA-IP>:8765`, wenn Kira TTS an
  `media_player` senden soll.

Die Home-Assistant-API wird intern ueber den Supervisor genutzt. Es ist kein
Long-Lived Access Token noetig.

## Persistenz

Kira speichert Daten unter `/data`:

- Memory und Conversation History
- Knowledge
- Plugin-Konfiguration
- Home-Assistant-Aktionsprotokoll
- OpenArt-History
- Voice-Dateien

Beim ersten Start werden Standarddateien aus dem Container nach `/data`
kopiert.
