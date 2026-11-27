"""Saved feedback reaches the full question tree, and only an explicit
developer decision can be exported. These checks use isolated rows and do
not call a model.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data_layer.customer_questions import (
    CustomerQuestionError,
    locate_exchange,
    read_panel_revision,
    read_question_tree,
    record_exchange,
)
from data_layer.exchange_feedback import save_feedback
from data_layer.quality_review import (
    export_approved_jsonl,
    list_quality,
    quality_signal,
    save_decision,
)
from webapp.chat_service import ChatService
from webapp.server import HOST, create_server

PSQL = os.environ.get("AUTOSERVICE_PSQL", "/opt/homebrew/opt/postgresql@18/bin/psql")
SOCKET_DIR = os.environ.get("AUTOSERVICE_LOCAL_PGSOCKET", "/tmp/autoservice-pg")
PORT = os.environ.get("AUTOSERVICE_LOCAL_PGPORT", "54332")
DATABASE = os.environ.get("AUTOSERVICE_LOCAL_PGDATABASE", "autoservice_assistant")
SERVICE = "engine-oil-change"
UNKNOWN_CONVERSATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNKNOWN_REQUEST = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ROOT = Path(__file__).resolve().parents[1]


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


def conversation(number: int) -> str:
    return f"f1a00000-0000-4000-8000-{number:012d}"


def request(number: int) -> str:
    return f"f1b00000-0000-4000-8000-{number:012d}"


def wipe_fixtures() -> None:
    for prefix in ("f1a00000-", "f1c00000-"):
        where = f"conversation_id like '{prefix}%'"
        owner_sql(f"delete from autoservice.exchange_training_reviews where {where}")
        owner_sql(f"delete from autoservice.customer_exchange_feedback where {where}")
        owner_sql(f"delete from autoservice.customer_exchange_intents where {where}")
        owner_sql(f"delete from autoservice.customer_exchanges where {where}")


class FeedbackTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        wipe_fixtures()
        cls.started = datetime(2001, 1, 1, tzinfo=timezone.utc)
        existing = int(owner_sql(
            "select count(*) from autoservice.customer_exchanges "
            f"where resolution = 'resolved' and service_id = '{SERVICE}'"
        ))
        cls.old_count = max(1, 21 - existing)
        cls.ids = []
        for index in range(cls.old_count):
            pair = (conversation(index + 1), request(index + 1))
            cls.ids.append(pair)
            record_exchange(
                pair[0], pair[1],
                f"Старый вопрос {index}",
                f"Старый ответ {index}",
                cls.started + timedelta(days=index),
                service_id=SERVICE,
                question_types=["price"],
                uncertain=False,
            )
        cls.oldest = cls.ids[0]
        cls.dual = (conversation(80), request(80))
        cls.price_only = (conversation(81), request(81))
        cls.unanswered = (conversation(82), request(82))
        cls.plain = (conversation(83), request(83))
        cls.review_only = (conversation(84), request(84))
        cls.same_request = "f1b00000-0000-4000-8000-0000000000aa"
        cls.same_a = ("f1c00000-0000-4000-8000-000000000001", cls.same_request)
        cls.same_b = ("f1c00000-0000-4000-8000-000000000002", cls.same_request)
        now = datetime.now(timezone.utc)
        record_exchange(
            *cls.dual,
            "Сколько стоит замена масла и можно записаться? Тел. +7 900 123-45-67",
            "Масло и фильтр меняем. Почта client@example.com не нужна.",
            now,
            service_id=SERVICE,
            question_types=["price", "booking"],
            uncertain=False,
        )
        record_exchange(
            *cls.price_only,
            "Только цена на масло",
            "Назову сумму после проверки объёма.",
            now + timedelta(seconds=1),
            service_id=SERVICE,
            question_types=["price"],
            uncertain=False,
        )
        record_exchange(
            *cls.unanswered,
            "Есть ли запись на завтра?",
            "Свободное окно уточню.",
            now + timedelta(seconds=2),
            service_id=SERVICE,
            question_types=["booking"],
            uncertain=False,
        )
        record_exchange(
            *cls.plain,
            "Старый обмен без оценки",
            "Ответ без оценки",
            now + timedelta(seconds=3),
            service_id=SERVICE,
            question_types=["hours"],
            uncertain=False,
        )
        record_exchange(
            *cls.review_only,
            "Непонятный вопрос для проверки ветки",
            "Нужно уточнить услугу.",
            now + timedelta(seconds=4),
            service_id=SERVICE,
            question_types=["diagnosis"],
            uncertain=True,
        )
        record_exchange(
            *cls.same_a,
            "Первый разговор, тот же запрос",
            "Ответ первого разговора",
            now + timedelta(seconds=5),
            service_id=SERVICE,
            question_types=["price"],
            uncertain=False,
        )
        record_exchange(
            *cls.same_b,
            "Второй разговор, тот же запрос",
            "Ответ второго разговора",
            now + timedelta(seconds=6),
            service_id=SERVICE,
            question_types=["booking"],
            uncertain=False,
        )
        save_feedback(*cls.oldest, 5, True, 1)
        save_feedback(*cls.dual, 5, True, 1)
        save_feedback(*cls.price_only, 1, None, 1)
        save_feedback(*cls.unanswered, 4, None, 1)

    @classmethod
    def tearDownClass(cls) -> None:
        wipe_fixtures()

    def test_feedback_migration_is_applied(self) -> None:
        self.assertEqual(
            owner_sql("select to_regclass('autoservice.customer_exchange_feedback')"),
            "autoservice.customer_exchange_feedback",
        )
        self.assertIn("stars", owner_sql("select pg_get_viewdef('autoservice_api.customer_exchanges'::regclass)"))
        self.assertTrue(read_panel_revision())

    def _next_revision(self, pair: tuple[str, str]) -> int:
        raw = owner_sql(
            "select coalesce(max(revision), 0) from autoservice.customer_exchange_feedback "
            f"where conversation_id = '{pair[0]}' and request_id = '{pair[1]}'"
        )
        return int(raw) + 1

    def _reset_known_feedback(self) -> None:
        owner_sql(
            "delete from autoservice.exchange_training_reviews "
            "where conversation_id like 'f1a00000-%' or conversation_id like 'f1c00000-%'"
        )
        save_feedback(*self.oldest, 5, True, self._next_revision(self.oldest))
        save_feedback(*self.dual, 5, True, self._next_revision(self.dual))
        save_feedback(*self.price_only, 1, None, self._next_revision(self.price_only))
        save_feedback(*self.unanswered, 4, None, self._next_revision(self.unanswered))

    def _rated(self, question_type: str | None = None) -> tuple[int, float | None]:
        type_filter = ""
        if question_type:
            type_filter = (
                "and exists (select 1 from autoservice.customer_exchange_intents intents "
                "where intents.conversation_id = exchanges.conversation_id "
                "and intents.request_id = exchanges.request_id "
                f"and intents.question_type = '{question_type}')"
            )
        raw = owner_sql(
            "select coalesce(string_agg(feedback.stars::text, ','), '') "
            "from autoservice.customer_exchanges exchanges "
            "join autoservice.customer_exchange_feedback feedback "
            "on feedback.conversation_id = exchanges.conversation_id "
            "and feedback.request_id = exchanges.request_id "
            f"where exchanges.resolution = 'resolved' and exchanges.service_id = '{SERVICE}' "
            "and feedback.stars is not null "
            f"{type_filter}"
        )
        stars = [int(item) for item in raw.split(",") if item]
        if not stars:
            return 0, None
        return len(stars), round(sum(stars) / len(stars), 4)

    def test_parent_counts_a_shared_exchange_once_and_an_edit_keeps_the_vote(self) -> None:
        self._reset_known_feedback()
        price_count, price_average = self._rated("price")
        booking_count, booking_average = self._rated("booking")
        service_count, service_average = self._rated()
        self.assertGreaterEqual(price_count, 1)
        self.assertGreaterEqual(booking_count, 1)
        self.assertEqual(service_count, price_count + booking_count - 1)
        price = read_question_tree(f"leaf:{SERVICE}:price", view="tree", limit=1, offset=0)
        booking = read_question_tree(f"leaf:{SERVICE}:booking", view="tree", limit=1, offset=0)
        service = read_question_tree(f"service:{SERVICE}", view="tree", limit=1, offset=0)
        self.assertEqual(price["node"]["rating_count"], price_count)
        self.assertEqual(price["node"]["average_stars"], price_average)
        self.assertEqual(booking["node"]["rating_count"], booking_count)
        self.assertEqual(booking["node"]["average_stars"], booking_average)
        self.assertEqual(service["node"]["rating_count"], service_count)
        self.assertEqual(service["node"]["average_stars"], service_average)
        self.assertNotIn(self.oldest[0], {item["conversation_id"] for item in service["history"]["exchanges"]})
        before = service_count
        before_revision = read_panel_revision()
        save_feedback(*self.dual, 3, True, self._next_revision(self.dual))
        after_count, after_average = self._rated()
        self.assertEqual(after_count, before)
        self.assertNotEqual(after_average, service_average)
        service = read_question_tree(f"service:{SERVICE}", view="tree", limit=1, offset=0)
        self.assertEqual(service["node"]["rating_count"], after_count)
        self.assertEqual(service["node"]["average_stars"], after_average)
        self.assertNotEqual(read_panel_revision(), before_revision)
        located = locate_exchange(*self.dual)
        page = read_question_tree(located["node_id"], view="tree", limit=20, offset=located["offset"])
        shown = next(
            item for item in page["history"]["exchanges"]
            if item["conversation_id"] == self.dual[0] and item["request_id"] == self.dual[1]
        )
        self.assertEqual(shown["feedback"], {"stars": 3, "resolved": True})

    def test_unanswered_resolved_stays_unknown_and_old_rows_remain_readable(self) -> None:
        self._reset_known_feedback()
        located = locate_exchange(*self.unanswered)
        page = read_question_tree(located["node_id"], view=located["view"], limit=located["limit"], offset=located["offset"])
        shown = next(item for item in page["history"]["exchanges"] if item["request_id"] == self.unanswered[1])
        self.assertEqual(shown["feedback"], {"stars": 4, "resolved": None})
        plain = locate_exchange(*self.plain)
        page = read_question_tree(plain["node_id"], view=plain["view"], limit=plain["limit"], offset=plain["offset"])
        shown = next(item for item in page["history"]["exchanges"] if item["request_id"] == self.plain[1])
        self.assertNotIn("feedback", shown)
        self.assertEqual(shown["assistant_reply"], "Ответ без оценки")

    def test_locate_opens_the_right_page_branch_and_conversation(self) -> None:
        located = locate_exchange(*self.oldest)
        self.assertEqual(located["view"], "tree")
        self.assertEqual(located["node_id"], f"service:{SERVICE}")
        self.assertGreaterEqual(located["offset"], 20)
        page = read_question_tree(located["node_id"], view="tree", limit=20, offset=located["offset"])
        self.assertIn(self.oldest[1], {item["request_id"] for item in page["history"]["exchanges"]})
        first = read_question_tree(located["node_id"], view="tree", limit=20, offset=0)
        self.assertNotIn(self.oldest[1], {item["request_id"] for item in first["history"]["exchanges"]})

        dual = locate_exchange(*self.dual)
        self.assertEqual(dual["node_id"], f"service:{SERVICE}")
        self.assertFalse(dual["node_id"].startswith("leaf:"))

        review = locate_exchange(*self.review_only)
        self.assertEqual(review["view"], "review")
        self.assertTrue(review["node_id"].startswith("review:"))

        first_conversation = locate_exchange(*self.same_a)
        second_conversation = locate_exchange(*self.same_b)
        self.assertEqual(first_conversation["request_id"], second_conversation["request_id"])
        self.assertNotEqual(first_conversation["conversation_id"], second_conversation["conversation_id"])
        first_page = read_question_tree(
            first_conversation["node_id"], view="tree", limit=20, offset=first_conversation["offset"]
        )
        second_page = read_question_tree(
            second_conversation["node_id"], view="tree", limit=20, offset=second_conversation["offset"]
        )
        first_item = next(
            item for item in first_page["history"]["exchanges"]
            if item["conversation_id"] == self.same_a[0] and item["request_id"] == self.same_request
        )
        second_item = next(
            item for item in second_page["history"]["exchanges"]
            if item["conversation_id"] == self.same_b[0] and item["request_id"] == self.same_request
        )
        self.assertEqual(first_item["customer_message"], "Первый разговор, тот же запрос")
        self.assertEqual(second_item["customer_message"], "Второй разговор, тот же запрос")

        with self.assertRaises(CustomerQuestionError) as raised:
            locate_exchange(UNKNOWN_CONVERSATION, UNKNOWN_REQUEST)
        self.assertEqual(str(raised.exception), "unknown exchange")

    def test_only_an_explicit_approval_is_exportable(self) -> None:
        self._reset_known_feedback()
        self.assertEqual(quality_signal(5, True), "positive")
        self.assertEqual(quality_signal(1, None), "examine")
        self.assertEqual(quality_signal(5, False), "conflict")
        self.assertEqual(quality_signal(3, True), "other")
        self.assertIsNone(quality_signal(None, None))

        before, before_count = export_approved_jsonl()
        self.assertNotIn(self.dual[0], before)
        positive = list_quality("positive", limit=100, offset=0)
        dual = next(item for item in positive["items"] if item["request_id"] == self.dual[1])
        self.assertEqual(dual["decision"], None)
        self.assertIn("+7 900 123-45-67", dual["customer_message"])

        saved = save_decision(*self.dual, "approved")
        self.assertEqual(saved["decision"], "approved")
        body, count = export_approved_jsonl()
        self.assertEqual(count, before_count + 1)
        exported = [json.loads(line) for line in body.splitlines() if line.strip()]
        match = next(item for item in exported if "Масло и фильтр" in item["answer"])
        encoded = json.dumps(match, ensure_ascii=False)
        self.assertNotIn(self.dual[0], encoded)
        self.assertNotIn(self.dual[1], encoded)
        self.assertNotIn("+7", encoded)
        self.assertNotIn("123-45-67", encoded)
        self.assertNotIn("example.com", encoded)
        self.assertNotIn("conversation_id", match)
        self.assertEqual(match["question_types"], ["booking", "price"])
        stored = owner_sql(
            "select customer_message from autoservice.customer_exchanges "
            f"where conversation_id = '{self.dual[0]}' and request_id = '{self.dual[1]}'"
        )
        self.assertIn("+7 900 123-45-67", stored)
        self.assertIn("client@example.com", owner_sql(
            "select assistant_reply from autoservice.customer_exchanges "
            f"where conversation_id = '{self.dual[0]}' and request_id = '{self.dual[1]}'"
        ))

        save_feedback(*self.dual, 5, False, self._next_revision(self.dual))
        body, _count = export_approved_jsonl()
        self.assertNotIn("Масло и фильтр", body)
        conflict = list_quality("conflict", limit=100, offset=0)
        reopened = next(item for item in conflict["items"] if item["request_id"] == self.dual[1])
        self.assertTrue(reopened["reopened"])
        self.assertNotEqual(reopened["bucket"], "approved")

        save_decision(*self.price_only, "excluded")
        body, _count = export_approved_jsonl()
        self.assertNotIn("Только цена", body)
        examine = list_quality("examine", limit=100, offset=0)
        self.assertFalse(any(
            item["request_id"] == self.price_only[1] and item["bucket"] == "approved"
            for item in examine["items"]
        ))

    def test_runtime_cannot_list_review_rows_and_the_assistant_is_untouched(self) -> None:
        completed = subprocess.run(
            [
                PSQL, "-h", SOCKET_DIR, "-p", PORT, "-U", "autoservice_runtime", "-d", DATABASE,
                "-v", "ON_ERROR_STOP=1", "-X", "-q", "-t", "-A",
                "-c", "select count(*) from autoservice.exchange_training_reviews",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=8,
        )
        self.assertNotEqual(completed.returncode, 0)
        for name in ("chat_service.py", "advisor.py", "retrieval.py", "reply_writer.py"):
            source = (ROOT / "webapp" / name).read_text(encoding="utf-8")
            self.assertNotIn("quality_review", source)
            self.assertNotIn("save_training_review", source)
            self.assertNotIn("customer_exchange_feedback", source)


class FeedbackTreeHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        wipe_fixtures()
        self.pair = (conversation(90), request(90))
        record_exchange(
            *self.pair,
            "Проверка ссылки",
            "Ответ для ссылки",
            datetime.now(timezone.utc),
            service_id=SERVICE,
            question_types=["price", "booking"],
            uncertain=False,
        )
        self.server = create_server(ChatService(env={}), 0, web_root=Path(tempfile.mkdtemp()))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        wipe_fixtures()

    def test_locate_and_export_http(self) -> None:
        status, located = self.request(
            "GET",
            f"/api/question-tree-locate?conversation_id={self.pair[0]}&request_id={self.pair[1]}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(located["node_id"], f"service:{SERVICE}")
        self.assertEqual(located["view"], "tree")
        status, missing = self.request(
            "GET",
            f"/api/question-tree-locate?conversation_id={UNKNOWN_CONVERSATION}&request_id={UNKNOWN_REQUEST}",
        )
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"]["message"], "Такой обмен не найден.")
        status, tree = self.request("GET", "/api/question-tree?view=tree&limit=1")
        self.assertEqual(status, 200)
        self.assertNotIn("rating_count", tree)
        self.assertNotIn("average_stars", tree)
        self.assertIn("rating_count", tree["node"])
        status, exported = self.request("GET", "/api/quality-review/export", raw=True)
        self.assertEqual(status, 200)
        self.assertEqual(exported["count"], "0")
        self.assertEqual(exported["body"], "")

    def request(self, method: str, path: str, payload: object | None = None, raw: bool = False):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"http://{HOST}:{self.port}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                body = response.read()
                status = response.status
                headers_out = dict(response.headers)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            status = exc.code
            headers_out = dict(exc.headers)
            exc.close()
        if raw:
            return status, {"body": body.decode("utf-8"), "count": headers_out.get("X-Export-Count")}
        return status, json.loads(body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
