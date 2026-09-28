# Abnahmestand der Testinstanz

## Letztes Backup und aiohttp-Kompatibilität – 0.3.0b3

- 39 isolierte Tests bestanden, einschließlich unbekanntem Initialwert,
  Wiederherstellen des Zeitstempels, ungültigen Daten und Schreibfehlern.
- 14 WebDAV-Laufzeittests bestanden; Abschlussmeldung nur nach erfolgreichem
  Metadaten-Commit, nicht bei fehlgeschlagenem oder unvollständigem Upload.
- HA-2026.9.3-Laufzeittest: elf Entitäten, sofortige Sensoraktualisierung,
  gespeicherter UTC-Zeitstempel, Wert bleibt während Ausfall erhalten.
- Status-Cache vor erneutem Setup entfernt: Wert aus HA-Store wiederhergestellt,
  Entitäts-IDs bleiben erhalten. Kein echter Cloud-Upload für diese Prüfung.
- Veraltete aiohttp-Authentifizierung durch einen expliziten Authorization-Header
  ersetzt; Quota- und Backup-Anfragen verwenden kein `BasicAuth`/`auth=` mehr.

## Erfolgreich geprüft

In der separaten lokalen Home-Assistant-2026.8.3-Instanz auf Port 18123:

- Start und Import der Integrationsmodule erfolgreich.
- Benutzer hat die Integration über die Oberfläche eingerichtet.
- Geräteseite zeigt alle neun Entitäten und das MagentaCLOUD-Symbol.
- Echter WebDAV-Abruf erfolgreich: Verbindung „Verbunden“, letzter Erfolg
  beim Ablesen vor 48 Sekunden, Latenz 71 ms.
- Angezeigte Quota: 2,46 GB belegt, 0,76 GB frei, 3,22 GB gesamt, 76,4 %.
- Beide Nettoänderungen sind nach Neueinrichtung erwartungsgemäß „Unbekannt“.

Dies ist eine Momentaufnahme, kein Nachweis wiederholter Abrufe oder der
langfristigen Historienberechnung. Zugangsdaten sind nicht Teil dieses Berichts.

## Noch offen

- Wiederholter Abruf und persistente Historie über Neustarts.
- Initial offline und Reauthentifizierung.
- Tatsächliche Netzwerkzeitlimits, TLS-/DNS-Fehler und beschädigte Historie.
- Langzeitvergleich für die beiden Nettoänderungen.

Die produktive Home-Assistant-Installation wurde für diese Prüfung nicht verändert.
Noch keine vollständige Freigabe für ein produktives Update.

## Kontrollierter Laufzeittest: Ausfall und Erholung

`runtime_outage.py` wurde zuletzt mit dem offiziellen HA-2026.9.3-Image ausgeführt.
Der kurzlebige Container hat keinen Netzwerkzugriff und nutzt ein temporäres
Konfigurationsverzeichnis, keine echten Zugangsdaten oder vorhandenen HA-Volumes.
Die Quota-Methode liefert kontrollierte Antworten; der DNS-Resolver ist für den
netzwerklosen Betrieb angepasst. HA-Koordinator, Entitäten, Ereignisse,
Registrierung und Historien-Store laufen unverändert.

Erfolgreich geprüft:

- Einrichtung mit neun Entitäten und echten HA-Zuständen.
- Simulierter temporärer API-Fehler: Verbindungszustand `off`, sieben aktuelle
  Sensoren `unavailable`, letzter Erfolg unverändert, kein neuer Historieneintrag.
- Erholung: Verbindungszustand `on`, neue Quota und neuer Erfolgszeitpunkt,
  zusätzlicher gespeicherter Historieneintrag.
- `state_changed`-Ereignisse für Ausfall und Erholung nachgewiesen.
- Entladen entfernt die Koordinator-Abonnenten; erneutes Laden erhält alle neun
  Entitäts-IDs und liest die vorhandene Historie weiter.

Die Aktualisierungen wurden gezielt ausgelöst, nicht durch Abwarten des
30-Minuten-Intervalls. Reale Transportausfälle, automatische Wiederholungszeiten
und ein vollständiger HA-Neustart werden damit noch nicht nachgewiesen.

## Backup-Agent 0.3.0b1

- 14 automatisierte Tests gegen einen echten lokalen aiohttp-WebDAV-Testserver
  bestanden: Roundtrip, Fortschritt, Löschumfang, Verschlüsselungspflicht,
  fehlende/beschädigte/zu große Metadaten, Upload-Abbruch, zu kurzer Upload/Download,
  kein Überschreiben, Metadatenfehler, Opt-in, fremde Pfade und HTTPS-Validierung.
- HA-Laufzeittest bestanden: Plattform laden, standardmäßig keine Backup-Agenten,
  Optionsflow aktivieren/deaktivieren, Agent-ID und Lebenszyklus-Benachrichtigungen.
- Bestehende 35 isolierte Tests bestehen weiterhin.
- Keine echten Cloud-Dateien für diese Entwicklung erstellt oder gelöscht.
- Provider-Upload und vollständiger Restore bleiben offen; siehe BACKUPS_DE.md.

## Echter MagentaCLOUD-Transfertest, 31. August 2026

Nach ausdrücklicher Freigabe ausschließlich künstliche Daten übertragen:
54.300 Bytes, mit einem temporären AES-GCM-Schlüssel verschlüsselt. Keine
HA-Konfiguration, Zugangsdaten oder privaten Dateien waren Teil des Inhalts.

Der Test deckte zwei Transportprobleme auf: Der gestreamte Upload benötigt eine
explizite Content-Length; bei deaktivierter automatischer HTTP-Dekomprimierung
wird Accept-Encoding: identity benötigt. Beides ist im Agenten korrigiert und
im lokalen HTTP-Testserver als erwartetes Verhalten abgesichert.

Nach Korrektur erfolgreich: Upload, HEAD-Größenprüfung, MOVE, Auflisten,
Download mit identischer SHA-256-Prüfsumme, Entschlüsselung des künstlichen
Inhalts und Löschen durch den Agenten. Auch die Dateien vorheriger fehlgeschlagener
Versuche wurden gezielt entfernt und ihre Abwesenheit per HEAD/404 geprüft.
Der gemeinsame Ordner HomeAssistant-MagentaCloud blieb bestehen.

Das ist ausdrücklich kein vollständiges HA-Backup und kein HA-Restore-Test:
HA-eigenes Verschlüsselungsformat, große Archive und Wiederherstellung bleiben offen.
Der Testlauf ist in cloud_transfer_check.py reproduzierbar, darf aber nur nach
ausdrücklicher Freigabe erneut gestartet werden, da er echte Cloud-Schreibzugriffe hat.

## Einfachere Backup-Aktivierung

HA-Laufzeittest erfolgreich: zehn Entitäten (neun Mess-/Statusentitäten und ein
Konfigurationsschalter), Backup-Auswahl bei Ersteinrichtung standardmäßig aus,
beide Ersteinrichtungswerte in den Optionen gespeichert. Geräteschalter,
Optionsdialog und Backup-Agent-Erkennung bleiben bei Ein-/Ausschalten synchron.
Umschalten verursacht weder Integration-Reload noch zusätzliche Quota-Abfrage.
Bestehende Optionen bleiben erhalten. Keine Uploads oder Änderung der HA-Zielauswahl
werden durch den Schalter selbst ausgeführt.
