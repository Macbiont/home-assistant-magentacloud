"""Small asynchronous WebDAV client for MagentaCLOUD quota information."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from urllib.parse import urlsplit
from xml.etree import ElementTree

from aiohttp import ClientError, ClientSession, ClientTimeout, encode_basic_auth


class MagentaCloudError(Exception):
    """Base exception for MagentaCLOUD errors."""


class MagentaCloudAuthenticationError(MagentaCloudError):
    """Raised when MagentaCLOUD rejects the credentials."""


class MagentaCloudUrlError(MagentaCloudError):
    """Raised for an unsafe or invalid endpoint."""


class MagentaCloudPermissionError(MagentaCloudError):
    """Raised when the server forbids access (not a password failure)."""


class MagentaCloudTemporaryError(MagentaCloudError):
    """Raised for throttling or temporary server failures."""


class MagentaCloudQuotaUnavailableError(MagentaCloudError):
    """Raised when the server does not expose WebDAV quota properties."""


@dataclass(frozen=True, slots=True)
class MagentaCloudData:
    """Values returned by a successful MagentaCLOUD request."""

    used: int
    available: int
    last_success: datetime
    latency_ms: float
    daily_change: int | None = None
    monthly_change: int | None = None

    @property
    def total(self) -> int:
        """Return the total quota in bytes."""
        return self.used + self.available

    @property
    def percent_used(self) -> float:
        """Return quota usage in percent."""
        return round(self.used / self.total * 100, 1) if self.total else 0.0


class MagentaCloudClient:
    """Read quota information from MagentaCLOUD using WebDAV."""

    _PROPFIND_BODY = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:quota-used-bytes/>
<d:quota-available-bytes/></d:prop></d:propfind>"""

    def __init__(
        self, session: ClientSession, url: str, username: str, password: str
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._url = url.rstrip("/") + "/"
        self._authorization = encode_basic_auth(username, password)

    async def async_get_quota(self) -> MagentaCloudData:
        """Fetch and parse quota properties."""
        # Validate here so existing config entries also fail through the normal
        # coordinator error path, before any credentials leave the process.
        try:
            endpoint = urlsplit(self._url)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.query
                or endpoint.fragment
                or any(char.isspace() or ord(char) < 32 for char in self._url)
                or endpoint.port == 0
            ):
                raise ValueError
        except ValueError:
            raise MagentaCloudUrlError("A valid HTTPS WebDAV URL is required") from None
        started = monotonic()
        try:
            async with self._session.request(
                "PROPFIND",
                self._url,
                data=self._PROPFIND_BODY,
                headers={
                    "Authorization": self._authorization,
                    "Depth": "0",
                    "Content-Type": "application/xml",
                },
                timeout=ClientTimeout(total=15, connect=5, sock_read=10),
                allow_redirects=False,
            ) as response:
                if response.status == 401:
                    raise MagentaCloudAuthenticationError
                if response.status == 403:
                    raise MagentaCloudPermissionError("WebDAV access is forbidden")
                if response.status == 429 or 500 <= response.status <= 599:
                    raise MagentaCloudTemporaryError(
                        f"WebDAV temporarily unavailable (HTTP {response.status})"
                    )
                if response.status != 207:
                    raise MagentaCloudError(
                        f"WebDAV returned unexpected HTTP status {response.status}"
                    )
                payload = await response.text()
        except MagentaCloudError:
            raise
        except (ClientError, TimeoutError) as err:
            raise MagentaCloudError("Unable to connect to MagentaCLOUD") from err

        try:
            root = ElementTree.fromstring(payload)
            used_text = root.findtext(".//{DAV:}quota-used-bytes")
            available_text = root.findtext(".//{DAV:}quota-available-bytes")
            if used_text is None or available_text is None:
                raise MagentaCloudQuotaUnavailableError
            used, available = int(used_text), int(available_text)
            if used < 0 or available < 0:
                raise MagentaCloudQuotaUnavailableError
            return MagentaCloudData(
                used=used,
                available=available,
                last_success=datetime.now().astimezone(),
                latency_ms=round((monotonic() - started) * 1000, 1),
            )
        except (ElementTree.ParseError, ValueError) as err:
            raise MagentaCloudQuotaUnavailableError from err
