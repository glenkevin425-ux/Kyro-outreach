import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import server as kyro
_ORIGINAL_VERCEL_RUNTIME = kyro.VERCEL_RUNTIME
import api.index as vercel_entry
from api.index import app
# Importing the deployment entrypoint deliberately forces PostgreSQL-only runtime mode.
# The unit suite uses isolated local SQLite fixtures instead.
kyro.VERCEL_RUNTIME = _ORIGINAL_VERCEL_RUNTIME


class VercelASGITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = kyro.DB_PATH
        self.old_url = kyro.DATABASE_URL
        self.old_vercel = _ORIGINAL_VERCEL_RUNTIME
        self.old_secret = kyro.CRON_SECRET
        kyro.DB_PATH = Path(self.tmp.name) / "asgi.sqlite3"
        kyro.DATABASE_URL = ""
        kyro.VERCEL_RUNTIME = False
        kyro.CRON_SECRET = "test-cron-secret"
        vercel_entry._DB_READY = False
        kyro.init_db()

    def tearDown(self):
        kyro.DB_PATH = self.old_path
        kyro.DATABASE_URL = self.old_url
        kyro.VERCEL_RUNTIME = self.old_vercel
        kyro.CRON_SECRET = self.old_secret
        vercel_entry._DB_READY = False
        self.tmp.cleanup()

    def invoke(self, path="/api/index", query=b"", method="GET", headers=None):
        messages = [{"type": "http.request", "body": b"", "more_body": False}]
        sent = []

        async def receive():
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query,
            "headers": headers or [],
            "client": ("127.0.0.1", 54321),
        }
        asyncio.run(app(scope, receive, send))
        start = next(item for item in sent if item["type"] == "http.response.start")
        body = next(item["body"] for item in sent if item["type"] == "http.response.body")
        return start["status"], json.loads(body)

    def test_vercel_runtime_refuses_ephemeral_sqlite_fallback(self):
        kyro.VERCEL_RUNTIME = True
        with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is required on Vercel"):
            kyro.db_connect()
        kyro.VERCEL_RUNTIME = False

    def test_rewritten_bootstrap_route_uses_asgi_entrypoint(self):
        status, body = self.invoke(query=b"kyro_route=bootstrap")
        self.assertEqual(status, 200)
        self.assertFalse(body["authenticated"])
        self.assertTrue(body["demo_enabled"])

    def test_vercel_get_cron_requires_and_accepts_bearer_secret(self):
        status, body = self.invoke(query=b"kyro_route=cron%2Frun")
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")

        status, body = self.invoke(
            query=b"kyro_route=cron%2Frun",
            headers=[(b"authorization", b"Bearer test-cron-secret")],
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["processed"], 0)
        self.assertEqual(body["sent"], 0)


if __name__ == "__main__":
    unittest.main()
