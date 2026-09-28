# Separate Home-Assistant-Testinstanz

Lokale Entwicklungsumgebung unter OrbStack, kein Ersatz für die produktive
Installation und keine vollständige Hardware-/HA-OS-Abnahme.

Aus dem Repository-Verzeichnis:

```sh
docker compose -p magentacloud-test -f testenv/compose.yaml up -d
docker compose -p magentacloud-test -f testenv/compose.yaml logs --tail=100
docker compose -p magentacloud-test -f testenv/compose.yaml stop
```

Die Oberfläche ist unter <http://127.0.0.1:18123> erreichbar. Ein eigenes
Test-Benutzerkonto erstellen; keine produktive Sicherung importieren. Für einen
echten MagentaCLOUD-Abruf eine separate WebDAV-Sitzung verwenden und deren Passwort
nur in der lokalen HA-Oberfläche eingeben, nicht im Repository speichern.

- Festes offizielles Image: Home Assistant 2026.9.3.
- Eigener Docker-Projektname, eigenes Netzwerk und eigenes Konfigurationsvolume.
- Portbindung an 127.0.0.1, kein Host-Netzwerk oder privilegierter Container.
- Keine USB-/Bluetooth-Geräte und keine automatische Geräteerkennung.
- Integration und YAML-Konfiguration werden schreibgeschützt eingebunden.
- Kein automatischer Neustart; maximal zwei CPUs und 2 GB Arbeitsspeicher.
- Stoppen erhält Testdaten. Volumes nicht ungeprüft löschen: Sie können lokale
  Testkonten und später eingegebene Zugangsdaten enthalten.

Die Arbeitskopie der Integration wird direkt eingebunden. Nach Codeänderungen
nur diesen Testdienst neu starten, nicht andere Container oder die produktive
Home-Assistant-Installation. Das bestehende ZIP wird hierbei nicht verwendet.

## Automatisierter Laufzeittest ohne Cloud-Zugangsdaten

Aus dem Repository-Verzeichnis ausführen (POSIX-Shell):

```sh
docker run --rm --network none --memory 2g --cpus 2 --entrypoint python \
  -v "$PWD:/work:ro" ghcr.io/home-assistant/home-assistant:2026.9.3 \
  /work/testenv/runtime_outage.py
```

Der Testprozess nutzt nur temporäre Daten und kontrollierte API-Antworten.
Er prüft Einrichtung, Ausfall, Erholung und Entladen/Neuladen mit echten
HA-Entitäten und Zustandsereignissen. Eine Meldung `Simulated outage` ist dabei
erwartet. Details und Grenzen stehen in [ACCEPTANCE.md](ACCEPTANCE.md).
