"""Feedback is one editable row for one existing exchange.

These checks use the local database and do not call a model.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from data_layer.exchange_feedback import ExchangeFeedbackError, read_feedback, save_feedback
from webapp.chat_service import ChatService
from webapp.server import HOST, create_server

PSQL = os.environ.get("AUTOSERVICE_PSQL", "/opt/homebrew/opt/postgresql@18/bin/psql")
SOCKET_DIR = os.environ.get("AUTOSERVICE_LOCAL_PGSOCKET", "/tmp/autoservice-pg")
PORT = os.environ.get("AUTOSERVICE_LOCAL_PGPORT", "54332")
DATABASE = os.environ.get("AUTOSERVICE_LOCAL_PGDATABASE", "autoservice_assistant")
UNKNOWN_CONVERSATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNKNOWN_REQUEST = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def owner_sql(statement: str) -> str:
    completed = subprocess.run(
        [
            PSQL, "-h", SOCKET_DIR, "-p", PORT, "-U", "autoservice_owner", "-d", DATABASE,
            "-v", "ON_ERROR_STOP=1", "-X", "-q", "-t", "-A", "-c", statement,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=8,
    )
    if completed.returncode != 0:
        raise AssertionError((completed.stderr or completed.stdout).strip())
    return completed.stdout.strip()


class ExchangeFeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        row = owner_sql(
            "select conversation_id || '|' || request_id || '|' || md5(assistant_reply) "
            "from autoservice.customer_exchanges order by exchanged_at desc limit 1"
        )
        self.conversation_id, self.request_id, self.reply_hash = row.split("|")
        self.exchange_count = int(owner_sql("select count(*) from autoservice.customer_exchanges"))
        owner_sql(
            "delete from autoservice.customer_exchange_feedback "
            f"where conversation_id = '{self.conversation_id}' and request_id = '{self.request_id}'"
        )

    def tearDown(self) -> None:
        owner_sql(
            "delete from autoservice.customer_exchange_feedback "
            f"where conversation_id = '{self.conversation_id}' and request_id = '{self.request_id}'"
        )
        self.assertEqual(int(owner_sql("select count(*) from autoservice.customer_exchanges")), self.exchange_count)
        self.assertEqual(
            owner_sql(
                "select md5(assistant_reply) from autoservice.customer_exchanges "
                f"where conversation_id = '{self.conversation_id}' and request_id = '{self.request_id}'"
            ),
            self.reply_hash,
        )

    def test_rating_round_trip_keeps_one_row(self) -> None:
        loaded = read_feedback(self.conversation_id, self.request_id)
        self.assertNotIn("feedback", loaded)
        self.assertEqual(loaded["revision"], 0)

        first = save_feedback(self.conversation_id, self.request_id, 4, None, 1)
        self.assertTrue(first["applied"])
        self.assertEqual(first["feedback"], {"stars": 4, "resolved": None})
        self.assertEqual(self._pair_count(), 1)

        changed = save_feedback(self.conversation_id, self.request_id, 5, False, 2)
        self.assertTrue(changed["applied"])
        self.assertEqual(changed["feedback"], {"stars": 5, "resolved": False})
        self.assertEqual(self._pair_count(), 1)

        again = save_feedback(self.conversation_id, self.request_id, 5, False, 2)
        self.assertTrue(again["applied"])
        self.assertEqual(self._pair_count(), 1)

        stale = save_feedback(self.conversation_id, self.request_id, 1, True, 1)
        self.assertFalse(stale["applied"])
        self.assertEqual(stale["feedback"], {"stars": 5, "resolved": False})
        self.assertEqual(self._pair_count(), 1)

        reread = read_feedback(self.conversation_id, self.request_id)
        self.assertEqual(reread["feedback"], {"stars": 5, "resolved": False})
        self.assertEqual(reread["revision"], 2)
        self.assertNotIn("customer_message", reread)
        self.assertNotIn("assistant_reply", reread)

    def test_unknown_exchange_does_not_insert(self) -> None:
        before = int(owner_sql("select count(*) from autoservice.customer_exchange_feedback"))
        with self.assertRaises(ExchangeFeedbackError) as raised:
            save_feedback(UNKNOWN_CONVERSATION, UNKNOWN_REQUEST, 5, True, 1)
        self.assertEqual(str(raised.exception), "unknown exchange")
        with self.assertRaises(ExchangeFeedbackError) as read_raised:
            read_feedback(UNKNOWN_CONVERSATION, UNKNOWN_REQUEST)
        self.assertEqual(str(read_raised.exception), "unknown exchange")
        self.assertEqual(int(owner_sql("select count(*) from autoservice.customer_exchange_feedback")), before)

    def test_runtime_cannot_list_feedback_rows(self) -> None:
        completed = subprocess.run(
            [
                PSQL, "-h", SOCKET_DIR, "-p", PORT, "-U", "autoservice_runtime", "-d", DATABASE,
                "-v", "ON_ERROR_STOP=1", "-X", "-q", "-t", "-A",
                "-c", "select count(*) from autoservice.customer_exchange_feedback",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=8,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("customer_message", completed.stdout)

    def _pair_count(self) -> int:
        return int(owner_sql(
            "select count(*) from autoservice.customer_exchange_feedback "
            f"where conversation_id = '{self.conversation_id}' and request_id = '{self.request_id}'"
        ))


class FeedbackHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        row = owner_sql(
            "select conversation_id || '|' || request_id "
            "from autoservice.customer_exchanges order by exchanged_at asc limit 1"
        )
        self.conversation_id, self.request_id = row.split("|")
        owner_sql(
            "delete from autoservice.customer_exchange_feedback "
            f"where conversation_id = '{self.conversation_id}' and request_id = '{self.request_id}'"
        )
        self.server = create_server(ChatService(env={}), 0, web_root=Path(tempfile.mkdtemp()))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        owner_sql(
            "delete from autoservice.customer_exchange_feedback "
            f"where conversation_id = '{self.conversation_id}' and request_id = '{self.request_id}'"
        )

    def test_http_entry_updates_the_same_row(self) -> None:
        status, body = self.request(
            "GET",
            f"/api/feedback?conversation_id={self.conversation_id}&request_id={self.request_id}",
        )
        self.assertEqual(status, 200)
        self.assertNotIn("feedback", body)

        status, saved = self.request("POST", "/api/feedback", {
            "conversation_id": self.conversation_id,
            "request_id": self.request_id,
            "stars": 3,
            "resolved": None,
            "revision": 1,
        })
        self.assertEqual(status, 200)
        self.assertTrue(saved["applied"])
        self.assertEqual(saved["feedback"]["stars"], 3)
        self.assertIsNone(saved["feedback"]["resolved"])

        status, changed = self.request("POST", "/api/feedback", {
            "conversation_id": self.conversation_id,
            "request_id": self.request_id,
            "stars": 3,
            "resolved": True,
            "revision": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(changed["feedback"], {"stars": 3, "resolved": True})
        self.assertEqual(int(owner_sql(
            "select count(*) from autoservice.customer_exchange_feedback "
            f"where conversation_id = '{self.conversation_id}' and request_id = '{self.request_id}'"
        )), 1)

        status, missing = self.request("POST", "/api/feedback", {
            "conversation_id": UNKNOWN_CONVERSATION,
            "request_id": UNKNOWN_REQUEST,
            "stars": 5,
            "resolved": False,
            "revision": 1,
        })
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"]["code"], "UNKNOWN_EXCHANGE")
        self.assertEqual(int(owner_sql(
            "select count(*) from autoservice.customer_exchange_feedback "
            f"where conversation_id = '{UNKNOWN_CONVERSATION}'"
        )), 0)

        status, rejected = self.request("GET", "/api/feedback")
        self.assertEqual(status, 400)
        status, rejected = self.request("POST", "/api/feedback", [])
        self.assertEqual(status, 400)
        status, tree = self.request("GET", "/api/question-tree?view=tree&limit=1")
        self.assertEqual(status, 200)
        self.assertNotIn("feedback", tree)
        self.assertNotIn("rating_count", tree)
        self.assertNotIn("average_stars", tree)

    def request(self, method: str, path: str, payload: object | None = None) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"http://{HOST}:{self.port}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            exc.close()
        return status, json.loads(raw.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
