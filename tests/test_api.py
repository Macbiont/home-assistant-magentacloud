"""Exercise production client logic with transport doubles, not a live server."""

import ast
import asyncio
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


class ClientError(Exception):
    """Transport error double."""


def load_api():
    path = Path(__file__).parents[1] / "custom_components/magentacloud/api.py"
    tree = ast.parse(path.read_text())
    tree.body = [
        node for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and node.module == "aiohttp")
    ]
    module = ModuleType("magentacloud_api_under_test")
    module.__dict__.update(
        ClientError=ClientError,
        ClientSession=object,
        ClientTimeout=SimpleNamespace,
        encode_basic_auth=lambda username, password: f"Basic {username}:{password}",
    )
    sys.modules[module.__name__] = module
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module


api = load_api()
QUOTA = '<d:prop xmlns:d="DAV:"><d:quota-used-bytes>10</d:quota-used-bytes><d:quota-available-bytes>30</d:quota-available-bytes></d:prop>'


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def client(self, status=207, payload=QUOTA, url="https://magentacloud.de/remote.php/webdav"):
        response = SimpleNamespace(status=status, text=AsyncMock(return_value=payload))
        # Special methods must live on the type for async with.
        class ResponseContext:
            async def __aenter__(self):
                return response

            async def __aexit__(self, *args):
                return False

        session = Mock()
        session.request.return_value = ResponseContext()
        return api.MagentaCloudClient(session, url, "user", "secret"), session, response

    async def test_success_and_transport_guards(self):
        client, session, _ = self.client()
        data = await client.async_get_quota()
        self.assertEqual((data.used, data.available, data.total, data.percent_used), (10, 30, 40, 25))
        self.assertIsNotNone(data.last_success.tzinfo)
        kwargs = session.request.call_args.kwargs
        self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn("auth", kwargs)
        self.assertEqual(kwargs["headers"]["Authorization"], "Basic user:secret")
        self.assertEqual(vars(kwargs["timeout"]), {"total": 15, "connect": 5, "sock_read": 10})

    async def test_invalid_urls_never_send_credentials(self):
        for url in (
            "http://magentacloud.de", "https:///missing", "https://user:secret@example.org",
            "https://example.org?q=secret", "https://example.org#fragment",
            "https://example.org:invalid", "https://example.org:0", "https://example.org:99999",
            "https://exam\nple.org", "https://[invalid",
        ):
            with self.subTest(url=url):
                client, session, _ = self.client(url=url)
                with self.assertRaises(api.MagentaCloudUrlError) as error:
                    await client.async_get_quota()
                session.request.assert_not_called()
                self.assertNotIn("secret", str(error.exception))

    async def test_http_error_classification(self):
        for status, error_type in (
            (401, api.MagentaCloudAuthenticationError),
            (403, api.MagentaCloudPermissionError),
            (429, api.MagentaCloudTemporaryError),
            (500, api.MagentaCloudTemporaryError),
            (503, api.MagentaCloudTemporaryError),
            (301, api.MagentaCloudError),
            (302, api.MagentaCloudError),
            (404, api.MagentaCloudError),
        ):
            with self.subTest(status=status):
                client, session, response = self.client(status=status)
                with self.assertRaises(error_type) as error:
                    await client.async_get_quota()
                self.assertIs(type(error.exception), error_type)
                session.request.assert_called_once()
                response.text.assert_not_called()

    async def test_transport_and_body_timeout(self):
        for failure in (TimeoutError(), ClientError("sensitive transport details")):
            client, _, response = self.client()
            response.text.side_effect = failure
            with self.assertRaises(api.MagentaCloudError) as error:
                await client.async_get_quota()
            self.assertEqual(str(error.exception), "Unable to connect to MagentaCLOUD")

    async def test_connection_failure(self):
        client, session, _ = self.client()
        session.request.side_effect = ClientError()
        with self.assertRaises(api.MagentaCloudError):
            await client.async_get_quota()

    async def test_cancel_propagates(self):
        client, _, response = self.client()
        response.text.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await client.async_get_quota()

    async def test_bad_quota_payloads(self):
        for payload in ("not xml", "<empty/>", QUOTA.replace(">10<", ">-1<"), QUOTA.replace(">30<", ">unknown<")):
            with self.subTest(payload=payload):
                client, _, _ = self.client(payload=payload)
                with self.assertRaises(api.MagentaCloudQuotaUnavailableError):
                    await client.async_get_quota()
