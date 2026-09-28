# MagentaCLOUD als Home-Assistant-Backup-Ziel

## Umfang und Status

Ab Version 0.3.0 bietet diese Integration selbst einen Home-Assistant-Backup-Agenten:
Hochladen, Auflisten, Herunterladen und Löschen. Eine zusätzliche WebDAV-Integration
ist dafür nicht erforderlich. Verwendet werden die bereits hinterlegten
MagentaCLOUD-Zugangsdaten. Der Agent ist bei bestehenden und neuen Einträgen
standardmäßig ausgeschaltet.

Geprüft mit Home Assistant 2026.9.3: echte HA-Backup-Datentypen, Plattform-Erkennung,
Optionsdialog, Listener sowie echte HTTP-Streams gegen einen lokalen WebDAV-Server.
Ein echter MagentaCLOUD-Transfer wurde mit künstlichen, verschlüsselten Daten
erfolgreich geprüft (einschließlich MOVE und Downloadvergleich). Zusätzlich wurde
ein verschlüsseltes Home-Assistant-Backup produktiv hochgeladen und heruntergeladen.
Uploads senden eine explizite Content-Length, Downloads fordern identity-Encoding an.
Noch nicht geprüft ist die vollständige Wiederherstellung eines verschlüsselten
Home-Assistant-Backups in einer separaten Installation. Kein Cloud-Dienst sollte
ohne eigenen Wiederherstellungstest das einzige Backup-Ziel sein.

## Aktivieren

1. Nach Aktualisierung des Codes Home Assistant regulär neu starten.
2. Die MagentaCLOUD-Geräteseite öffnen. Im Bereich „Konfiguration“ steht der
   Schalter „Backup-Ziel aktivieren“. Alternativ bleibt „Konfigurieren“ verfügbar.
   Bei einer neuen Einrichtung gibt es direkt die Auswahl „MagentaCLOUD auch für
   Backups verwenden“, standardmäßig aus.
3. Den Schalter einschalten. Er stellt den Agenten `MagentaCLOUD (<Kontotitel>)`
   ohne Neuladen der Integration bereit und startet selbst keinen Upload.
   Geräteschalter und Optionsdialog bleiben synchron; bestehende Einstellungen
   werden beim Update nicht verändert.
4. In den Home-Assistant-Backup-Einstellungen dieses Ziel bewusst auswählen und
   Verschlüsselung aktivieren. Unverschlüsselte Uploads werden abgewiesen.
5. Den passenden Wiederherstellungsschlüssel bzw. das Backup-Notfallkit außerhalb
   von Home Assistant sicher aufbewahren. Niemals in Git speichern.
6. Freien Cloud-Speicher mit der Backup-Größe vergleichen, einschließlich Reserve
   für weitere Sicherungen und unterbrochene Transfers. Die Integration reserviert
   keinen Speicher und löscht keine alten Dateien zur Platzbeschaffung.
7. Erst ein kleines, verschlüsseltes Testbackup erzeugen. Dann herunterladen und
   die Wiederherstellung in einer weiteren isolierten Instanz prüfen. Nie dafür
   die produktive Installation überschreiben.

Das Ziel muss in der Backup-Verwaltung separat ausgewählt werden. Automatische
Zeitpläne, Verschlüsselung, Auswahl der Inhalte und Aufbewahrungsregeln steuert
Home Assistant. Diese Integration führt keine eigenen zeitgesteuerten Löschungen
durch; Home Assistant kann entsprechend seinen Aufbewahrungsregeln Löschungen
beim Agenten anfordern.

## Speicherformat und Sicherheit

### Letztes Backup

Der Zeitstempel-Sensor „Letztes Backup“ zeigt den Abschluss des letzten durch
diese Integration erfolgreich hochgeladenen Backups. Er wird erst nach dem
abschließenden MOVE der Metadaten gesetzt, nicht bei Uploadstart oder Erstellung
des HA-Archivs. Fehlgeschlagene Transfers ändern ihn nicht. Der Zeitpunkt wird
lokal pro Integrationseintrag gespeichert und bleibt bei WebDAV-Ausfällen oder
deaktiviertem Backup-Ziel erhalten. Das Löschen eines Cloud-Backups setzt ihn
nicht zurück: Er beschreibt einen Upload-Erfolg, nicht die aktuelle Existenz.

Ohne gespeicherten Erfolg ist der Wert „Unbekannt“. Für ältere Backups wird kein
Abschlusszeitpunkt aus dem Erstellungsdatum geschätzt. Kann die lokale Speicherung
nicht geschrieben werden, wird dies protokolliert; der fertige Cloud-Upload wird
dadurch nicht als fehlgeschlagen gemeldet.

- Fester Ordner unter dem konfigurierten WebDAV-Endpunkt:
  `HomeAssistant-MagentaCloud`. Er wird erst beim ersten Upload angelegt.
- Dateinamen sind SHA-256-Ableitungen der Backup-ID, nicht des Backup-Namens.
- Pro Backup eine `.tar`-Datei und eine `.metadata.json`-Datei. Nur eigene
  Metadaten in genau diesem Ordner werden aufgelistet; fremde Ordner werden
  nicht durchsucht oder gelöscht. Nicht mit einem anderen Backup-Programm teilen.
- Das Archiv wird von HA verschlüsselt geliefert. Die JSON-Metadaten liegen
  unverschlüsselt vor und enthalten unter anderem Name, Datum und Inhaltsübersicht;
  deshalb keine Geheimnisse in Backup-Namen verwenden.
- HTTPS mit Zertifikatsprüfung, keine Weiterleitungen. Übertragung in Blöcken,
  kein vollständiges Laden des Archivs in den Arbeitsspeicher. Downloads werden
  nicht automatisch durch HTTP-Inhaltsdekodierung verändert.
- Uploads landen zunächst in einer eindeutigen `.partial`-Datei. Erst nach
  Größenprüfung wird das Archiv per WebDAV MOVE übernommen. Metadaten werden
  zuletzt ebenfalls per MOVE veröffentlicht. Bestehende Dateien werden nicht
  überschrieben (`Overwrite: F`).
- Die Bytezahl wird beim Hoch- und Herunterladen geprüft. Das ersetzt keinen
  kryptografischen Integritätstest oder erfolgreichen Wiederherstellungstest.
- Übertragungen haben ein Gesamtlimit von 12 Stunden, Verbindungsaufbau 15 Sekunden,
  Socket-Lesen 120 Sekunden. Kleine Verwaltungsanfragen haben 60 Sekunden Gesamtlimit.
  Es gibt keine automatische Wiederaufnahme oder eigene Retry-After-Planung.

## Fehler und Rücknahme

Bei Abbruch können `.partial`-Dateien oder ein Archiv ohne fertige Metadaten
zurückbleiben. Sie werden absichtlich nicht als fertige Backups angezeigt und
nicht automatisch gelöscht. Sie belegen weiterhin Speicher. Erst nach Prüfung
und ohne laufenden Transfer manuell bereinigen. Ein vorhandenes Archiv wird bei
erneutem Upload derselben ID nicht überschrieben; dann ein neues Backup erstellen
oder den verwaisten Versuch gezielt prüfen.

Beschädigte Metadaten verursachen einen sichtbaren Fehler statt einer scheinbar
vollständigen Liste. Beim Löschen wird zuerst das Archiv entfernt; scheitert das,
bleiben Metadaten für einen weiteren Versuch erhalten. Bei fehlgeschlagener
Metadatenlöschung kann vorübergehend ein Eintrag ohne Archiv übrig bleiben.

„Backup-Ziel aktivieren“ ausschalten entfernt den Agenten, nicht seine Dateien.
Vorher laufende Backups abschließen und das Ziel aus Zeitplänen entfernen.
Die Einrichtung der Integration benötigt weiterhin eine erfolgreiche
Speicherplatz-Abfrage; bei einem Offline-Start steht der Agent erst nach
erfolgreicher Einrichtung zur Verfügung. Backup-Authentifizierungsfehler werden
als Backup-Fehler gemeldet; der Sensor-Koordinator übernimmt die Neuanmeldung.

## Entwicklungstests

Aus dem Repository-Verzeichnis:

```sh
python3 -m unittest discover -s tests -v
docker run --rm --network none --memory 2g --cpus 2 --entrypoint python \
  -v "$PWD:/work:ro" ghcr.io/home-assistant/home-assistant:2026.9.3 \
  /work/testenv/test_backup_runtime.py
docker run --rm --network none --memory 2g --cpus 2 --entrypoint python \
  -v "$PWD:/work:ro" ghcr.io/home-assistant/home-assistant:2026.9.3 \
  /work/testenv/runtime_outage.py
```

Diese Prozesse binden keine bestehenden HA-Datenvolumes ein und enthalten nur
synthetische Zugangsdaten. Der HTTP-Testserver läuft ausschließlich auf Loopback
im Container. TLS und providerabhängige Eigenschaften werden dabei nicht simuliert.
