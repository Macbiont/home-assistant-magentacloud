# MagentaCLOUD for Home Assistant

Unofficial Home Assistant integration for monitoring MagentaCLOUD storage and
using MagentaCLOUD as an encrypted Home Assistant backup destination.

> This is a community project. It is not affiliated with, endorsed by, or
> supported by Deutsche Telekom AG. MagentaCLOUD and related marks belong to
> their respective owner.

## Features

- Storage used, available, total, and percentage used
- Net storage change over rolling 24-hour and 30-day windows
- Connection status, WebDAV latency, and last successful update
- Optional Home Assistant backup destination
- Last successfully completed backup upload
- UI setup, options flow, and credential reauthentication
- HTTPS-only WebDAV requests without redirects

The integration polls the WebDAV quota every 30 minutes. Storage values use
decimal gigabytes (`1 GB = 1,000,000,000 bytes`), matching Home Assistant's
`GB` unit.

## Requirements

- Home Assistant 2026.9.3 or newer
- A MagentaCLOUD account
- A dedicated MagentaCLOUD WebDAV session password
- HACS for the recommended installation method

## Installation with HACS

Until the repository is part of the default HACS catalog:

1. Open HACS.
2. Open the three-dot menu and select **Custom repositories**.
3. Add `https://github.com/Macbiont/home-assistant-magentacloud`.
4. Select **Integration** as the category.
5. Install **MagentaCLOUD** and restart Home Assistant.
6. Open **Settings > Devices & services > Add integration** and select
   **MagentaCLOUD**.

## Manual installation

Copy `custom_components/magentacloud` into the `custom_components` directory
of the Home Assistant configuration and restart Home Assistant.

## Credentials

1. Sign in at [magentacloud.de](https://magentacloud.de).
2. Open **Settings > Devices and sessions**.
3. Create a separate WebDAV session for Home Assistant.
4. Enter the displayed primary email address and generated session password.

Default WebDAV endpoint:

```text
https://magentacloud.de/remote.php/webdav
```

Use a dedicated session password so it can be revoked independently. The
integration does not expose credentials as entity attributes or write them to
logs.

## Entities

| Entity | Unit | Description |
|---|---:|---|
| Used storage | GB | Bytes currently used |
| Available storage | GB | Remaining quota |
| Total storage | GB | Used plus available quota |
| Storage used | % | Used percentage of total quota |
| Change in 24 hours | GB | Net change over a rolling 24-hour window |
| Change in 30 days | GB | Net change over a rolling 30-day window |
| Last update | Timestamp | Latest successful WebDAV quota request |
| Last backup | Timestamp | Latest completed backup upload |
| WebDAV latency | ms | Duration of the latest successful request |
| Connection | Online/offline | Result of the latest quota request |
| Enable backup location | On/off | Exposes the backup agent to Home Assistant |

Change sensors remain unknown until a sufficiently close baseline exists. They
represent net quota changes, not upload traffic: uploads and deletions can
offset each other.

## Backups

The backup provider is opt-in. Enabling the integration's **Enable backup
location** switch only makes MagentaCLOUD available as a destination. Select it
separately under Home Assistant's backup settings and enable Home Assistant
backup encryption.

Backups are stored below the configured WebDAV endpoint in:

```text
HomeAssistant-MagentaCloud
```

Uploads are streamed to a temporary object, size-checked, moved into place, and
made visible only after their metadata has been committed. The provider supports
listing, download, and deletion through Home Assistant's backup interface.

The transport round-trip and failure paths are tested automatically. Before
depending on any cloud destination as the only recovery copy, perform a restore
drill appropriate for your Home Assistant installation and keep the encryption
emergency kit offline. See [BACKUPS_DE.md](BACKUPS_DE.md) for the detailed
German backup notes.

## Availability and privacy

During a WebDAV outage, current quota and latency sensors become unavailable.
The connection sensor reports offline, while the last successful update and
last completed backup remain available when previously known.

Locally stored history contains timestamps and byte counts only. It never
contains cloud file names, backup contents, email addresses, or credentials.

The integration accepts only HTTPS endpoints without embedded credentials,
query strings, or fragments. Redirects are not followed and Home Assistant's
shared HTTP session performs normal TLS certificate verification.

## Support

Use the [GitHub issue tracker](https://github.com/Macbiont/home-assistant-magentacloud/issues)
for reproducible problems. Remove credentials, email addresses, file names,
backup contents, and unrelated personal information before posting logs or
screenshots.

## Development

Run the dependency-free unit suite:

```sh
python3 -m unittest discover -s tests -v
```

The isolated Home Assistant runtime checks are documented in
[testenv/README.md](testenv/README.md). They cover setup, entity registration,
outage and recovery, persistence, backup discovery, streamed backup round-trip,
and failure handling against Home Assistant 2026.9.3.

## License

[MIT](LICENSE)
