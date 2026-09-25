# Changelog

## 2.2.0

- Aufgabenliste, Verlauf, Details und Abbruch per `/tasks` oder Aufgabenfrage
- atomare Task-Ausfuehrung mit frischem Triggerzustand und Fehlerhistorie
- offene Aufgaben bleiben bei vollem Speicher erhalten
- weniger HA-REST-Abfragen bei unpassenden Live-Ereignissen
- Benutzer- und Kanalgrenzen fuer Aufgabenverwaltung

## 2.1.0

- SituationContext, Activities, Goals und Completion Checks
- Entity-, Device- und Area-Registry mit sicheren Fallbacks
- explizite Praeferenzen und persistente Wenn-dann-Tasks
- erneute Planung und Safety-Pruefung bei Task-Triggern
- erklaerbare proaktive Erkennung; automatische Ausfuehrung bleibt aus

## 2.0.0

- Kontextbewusster Agent fuer Home Assistant Assist, API, Desktop und CLI
- dynamische Entity-, Raum-, Geraete- und Faehigkeitsaufloesung
- persistente Folgefragen und Referenzen pro Conversation
- mehrstufige Workflows mit Vorrang fuer vorhandene HA-Ablaufe
- planweite Sicherheits- und Parameterpruefung
- frische State-Pruefung vor und nach Service Calls
- benutzer- und kanalgebundene, ablaufende Bestaetigungen
- atomare lokale Agenten- und Aktionsdaten
- geschuetzte schreibende Update-Endpunkte
- automatisierte Add-on-Metadatenpruefung und Docker-Testbuilds

## 1.9.1

- Add-on-Preflight, Healthcheck, Watchdog und Diagnose-Endpunkt
- stabilerer Optionsparser und explizite Home-Assistant-Kontrolle
