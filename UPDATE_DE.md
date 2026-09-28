# Sicher aktualisieren und zurückrollen

## Stand dieser Version

Der Quellcode trägt Version 0.3.0. Sensoren und Backup-Agent wurden mit Home
Assistant 2026.9.3, einem lokalen WebDAV-Testserver und einer produktiven
MagentaCLOUD-Verbindung geprüft. Ein verschlüsseltes Home-Assistant-Backup wurde
erfolgreich hoch- und wieder heruntergeladen. Eine vollständige Wiederherstellung
in einer separaten Home-Assistant-Installation bleibt als eigener Nutzertest
empfohlen. Siehe auch BACKUPS_DE.md und testenv/ACCEPTANCE.md.

## Vor einem späteren Update

1. Installationstyp und Home-Assistant-Version notieren. `/config` bezeichnet
   hier das tatsächlich verwendete Konfigurationsverzeichnis; bei Container-
   Installationen ist der zugehörige Host-Pfad zu prüfen.
2. Ein aktuelles Backup einschließlich Home-Assistant-Konfiguration erstellen,
   erfolgreichen Abschluss prüfen und eine Kopie außerhalb des HA-Geräts
   aufbewahren. Bei verschlüsselten Backups auch den passenden Schlüssel sichern.
   Siehe [offizielle Backup-Anleitung](https://www.home-assistant.io/common-tasks/general/#backups).
3. Den bisherigen Ordner `custom_components/magentacloud` separat und mit Datum
   außerhalb von `custom_components` sichern. Die tatsächlich installierte
   Version notieren; nicht auf einen älteren, ungeprüften Sicherungsordner verlassen.
4. Einen von der HA-Weboberfläche unabhängigen Wiederherstellungszugang prüfen,
   etwa direkte SSH-Verbindung oder lokale Konsole. Ein Terminal, das nur über
   die HA-Oberfläche erreichbar ist, reicht dafür nicht. Ohne diesen Zugang und
   eine verfügbare Sicherung nicht fortfahren.
5. Vorhandene Entitäts-IDs und aktuelle Werte notieren. Integration nicht löschen
   oder neu anlegen. Zugangsdaten nicht in Screenshots, Logs oder Git übernehmen.

## Abnahme in einer separaten Testinstallation

Eine eigene WebDAV-Sitzung benutzen. Fehlerfälle über kontrollierte Testantworten
oder ausschließlich in der Testumgebung auslösen, nicht durch Abschalten des
Heimnetzes oder Änderung produktiver Zugangsdaten.

- [ ] Einrichtung mit gültiger HTTPS-Adresse; alle neun Entitäten prüfen.
- [ ] HTTP-Adresse wird abgelehnt, ohne Zugangsdaten zu senden.
- [ ] HTTP 401 fordert Neuanmeldung an; neues Sitzungspasswort wird gespeichert.
- [ ] HTTP 403, 429 und 5xx werden nicht als falsches Passwort behandelt.
- [ ] DNS-, TLS- und Timeoutfehler führen nicht zu einem blockierten HA-Start.
- [ ] Offline beim ersten Start: Einrichtung wird später erneut versucht.
- [ ] Ausfall nach Erfolg: Verbindung aus, letzter Erfolg bleibt sichtbar,
      aktuelle Messwerte nicht verfügbar; nach Wiederkehr neue Werte.
- [ ] Defekte Historie verhindert keine aktuellen Speicherwerte und bleibt
      auf dem Datenträger unverändert; Schreibfehler und Erholung prüfen.
- [ ] Fehlende Vergleichswerte ergeben unbekannte Nettoänderungen, nicht null.
- [ ] Integration entladen, erneut laden und HA neu starten; keine doppelten
      Entitäten, keine zurückbleibenden Updates, bisherige Entitäts-IDs erhalten.

Die lokalen Tests ersetzen diese Abnahme nicht. Insbesondere testen sie weder
echte Netzwerkzeitlimits noch Home Assistants Wiederholungs- und Reauth-Abläufe.

## Kontrolliertes Update nach erfolgreicher Abnahme

1. Freigegebenes Paket und Version prüfen. Ausschließlich den Integrationsordner
   ersetzen, keine Dateien aus verschiedenen Versionen mischen. Alte Kopie behalten.
2. Keine `.storage`-Dateien und keine Dashboard-Konfiguration manuell bearbeiten.
3. Konfigurationsprüfung durchführen. Ein erfolgreiches Ergebnis ist noch kein
   Nachweis, dass die Integration zur Laufzeit funktioniert.
4. Einen regulären Home-Assistant-Neustart auslösen. Nicht zuerst `ha core stop`
   im eingebetteten Terminal ausführen: Dadurch kann der Zugang für den folgenden
   Startbefehl verloren gehen. Kein Ausschalten über die Stromsicherung.
5. Nach dem Start Protokolle und MagentaCLOUD-Entitäten prüfen, einschließlich
   eines weiteren regulären Abrufs nach etwa 30 Minuten. Bei Fehlern nicht in
   schneller Folge neu starten, sondern Ursache prüfen oder zurückrollen.

## Rückweg bei Problemen

Wenn HA noch erreichbar ist: Fehlerprotokolle ohne Geheimnisse sichern. Über den
vorbereiteten Dateizugang den neuen Integrationsordner außerhalb von
`custom_components` aufbewahren und den zuvor gesicherten Ordner vollständig
wiederherstellen. Danach regulär neu starten. Keine Integration löschen und
keine Entitätsregistrierungen oder Historien manuell überschreiben.

Wenn HA nicht mehr erreichbar ist: Den zuvor geprüften unabhängigen Zugang
verwenden. Zuerst Core-Status und Protokolle prüfen; eine fehlende Webseite
beweist keinen Integrationsfehler. Falls erforderlich dieselbe Ordner-Rücknahme
vornehmen und Core über den zur Installation passenden Verwaltungsweg starten.
Nicht auf den eingebetteten Browser-Terminalzugang angewiesen sein.

Wenn die gezielte Rücknahme nicht genügt, das geprüfte Backup gemäß der
[offiziellen Wiederherstellungsanleitung](https://www.home-assistant.io/common-tasks/general/#restoring-a-backup)
verwenden. Eine vollständige Wiederherstellung setzt auch andere Änderungen seit
diesem Backup zurück; Umfang vorher bewusst auswählen.
