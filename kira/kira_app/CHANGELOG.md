# Changelog

## 2.1.0 - Kontextuelle Intelligenz

- kompakter SituationContext fuer Praesenz, Activities, Raeume, Geraete,
  Sicherheit, Energie und Ausfaelle
- konfigurierbare Goals mit Completion Checks vor und nach der Ausfuehrung
- explizite Praeferenzen und Goal-History als getrennte atomare Datenspeicher
- Home-Assistant Entity-, Device- und Area-Registry mit Cache und Fallbacks
- Context Fusion mit begrenzter Auswahl relevanter Entities
- persistente bedingte Tasks mit Triggern, Conditions, Safety Classification,
  Bestaetigung und Live-Event-Ausfuehrung
- vorhandene Home-Assistant-Automationen werden vor eigenen Tasks bevorzugt
- erklaerbare Proactive Signals mit Confidence und Evidence
- Confidence-Grenzen fuer riskante Plaene und proaktive Aktionen
- neue Akzeptanz-, Registry-, Goal-, Activity-, Task- und Proaktivtests
- nicht-destruktive Workflow-Default-Ebene fuer bestehende Add-on-Installationen
- Registry-Aliase, zeitlich begrenzter Goal-Kontext und strengere Activity-Evidence
- deduplizierte Proaktivhinweise und kontrollierter Shutdown der Hintergrunddienste
- robuste Registry-Abfragen fuer grosse Installationen und gefilterte
  Offline-Beobachtungen ohne Helper-Entity-Logflut

## 2.0.0 - Kontextbewusster Home-Assistant-Agent

- gemeinsamer Agentenpfad fuer CLI, Desktop, API und Home Assistant Assist
- persistenter Conversation-, Benutzer-, Quellen- und Raumkontext
- strukturierte semantische Intent-Erkennung mit lokalem Fallback
- dynamische Entity-, Geraete-, Raum- und Faehigkeitsaufloesung
- datengetriebene Workflows mit Vorrang fuer HA Scenes, Scripts und Automationen
- planweite Sicherheits-, Service-, Entity- und Parameterpruefung
- No-op-Erkennung, frische Vorab-States und verifizierte Resultate
- ablaufende, benutzer- und kanalgebundene Bestaetigungen
- atomare Kontext- und Aktionsprotokolle mit Korruptionsschutz
- vorbereitete, standardmaessig inaktive Proaktiv-Modi
- Assist-Ursprungsraum aus Device-/Satellite- und Area-Registry
- geschuetzte schreibende Update-Endpunkte und automatisierte Release-CI
- sicherheitsbereinigte FastAPI-/Starlette- und Entwicklungsabhaengigkeiten
- aktuelle Home-Assistant-App-Metadaten fuer `amd64` und `aarch64`

## 1.9.1 - Home Assistant Add-on Stabilitaet

- Add-on-Preflight, Healthcheck, Watchdog und Diagnose-Endpunkt
- sichere generische Home-Assistant-Servicebefehle

## 1.9.0 - Desktop Companion

- Floating Companion, Sprechblase, Schnellaktionen und Codex-Pet-Unterstuetzung
