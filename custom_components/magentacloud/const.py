"""Constants for the MagentaCLOUD integration."""

from datetime import timedelta

DOMAIN = "magentacloud"
DEFAULT_URL = "https://magentacloud.de/remote.php/webdav"
DEFAULT_SCAN_INTERVAL = timedelta(minutes=30)

CONF_URL = "url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_BACKUP_ENABLED = "backup_enabled"
BACKUP_FOLDER = "HomeAssistant-MagentaCloud"
DATA_BACKUP_LISTENERS = f"{DOMAIN}_backup_listeners"
