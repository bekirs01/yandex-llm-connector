"""HARNESS TEST for the Wave 4A chat runner.

These checks start a local stub of POST /api/chat. They do not start a model,
call the live chat, open the reserved test split, or score reply quality.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import run_eval

BANNER = "HARNESS TEST: local /api/chat stub only. Not a conversational quality evaluation."


def setUpModule() -> None:
    print(BANNER)


class StubChat:
    def __init__(self, respond, delay: float = 0.0) -> None:
        self.respond = respond
        self.delay = delay
        self.requests: list[dict] = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
        self.httpd.stub = self
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


class StubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        stub = self.server.stub
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        path = urllib.parse.urlparse(self.path).path
        stub.requests.append({
            "path": path,
            "content_type": self.headers.get("Content-Type", ""),
            "body": raw,
        })
        if path != "/api/chat":
            self._send(404, {"error": {"code": "NOT_FOUND", "message": "Not found."}})
            return
        if stub.delay:
            time.sleep(stub.delay)
        status, body = stub.respond(raw, len(stub.requests) - 1)
        self._send(status, body)

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def ok_reply(raw: bytes, index: int) -> tuple[int, dict]:
    payload = json.loads(raw.decode("utf-8"))
    return 200, {
        "request_id": payload["request_id"],
        "conversation_id": payload["conversation_id"],
        "message": {"role": "assistant", "text": f"Понял вас. Ответ {index}."},
        "metrics": {"elapsed_ms": 0},
    }


def fixture(customers: list[str], kind: str = "automotive") -> dict:
    return {
        "id": "harness-fixture",
        "tags": ["harness"],
        "turns": [
            {
                "customer": customer,
                "kind": kind,
                "must_understand": ["Harness fixture only."],
                "may_ask": ["Harness fixture only."],
                "concrete_failures": ["Harness fixture only."],
                "reviewer_judgments": [run_eval.GRADING_CANARY],
            }
            for customer in customers
        ],
    }


class HarnessDatasetTests(unittest.TestCase):
    def test_harness_dataset_shape_covers_contrast_and_both_kinds(self) -> None:
        dataset = run_eval.load_dataset()
        self.assertEqual(dataset["schema"], run_eval.SCHEMA)
        self.assertEqual(len(dataset["cases"]), 24)
        self.assertIn("greeting is not required", dataset["scoring"]["wording"].casefold())
        self.assertNotIn("test.jsonl", Path(run_eval.__file__).read_text(encoding="utf-8"))
        self.assertNotIn("webapp", Path(run_eval.__file__).read_text(encoding="utf-8"))


class HarnessStubTests(unittest.TestCase):
    def test_harness_refuses_non_local_chat_url(self) -> None:
        for url in ("https://example.com", "http://example.com", "http://127.0.0.1:8766/api/chat"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    run_eval.make_http_post(url)

    def test_harness_threads_actual_replies_and_hides_grading(self) -> None:
        dataset = run_eval.load_dataset()
        stub = StubChat(ok_reply)
        try:
            packet = run_eval.run_dataset(dataset, run_eval.make_http_post(stub.base_url), 5, "harness-test", stub.base_url)
        finally:
            stub.close()

        self.assertTrue(packet["harness_test"])
        self.assertEqual(len(stub.requests), sum(len(case["turns"]) for case in dataset["cases"]))
        canary = dataset["grading_canary"]
        for seen in stub.requests:
            self.assertEqual(seen["path"], "/api/chat")
            self.assertTrue(seen["content_type"].startswith("application/json"))
            body = json.loads(seen["body"].decode("utf-8"))
            self.assertEqual(set(body), {"request_id", "conversation_id", "messages"})
            encoded = seen["body"].decode("utf-8")
            self.assertNotIn(canary, encoded)
            self.assertNotIn("must_understand", encoded)
            self.assertNotIn("reviewer_judgments", encoded)
            self.assertNotIn("concrete_failures", encoded)
            for message in body["messages"]:
                self.assertEqual(set(message), {"role", "text"})

        before = 0
        target = None
        for case in packet["cases"]:
            if case["id"] == "w4a-22":
                target = case
                break
            before += len(case["turns"])
        self.assertIsNotNone(target)
        third = target["turns"][2]
        self.assertEqual(
            [message["text"] for message in third["sent_messages"] if message["role"] == "assistant"],
            [f"Понял вас. Ответ {before}.", f"Понял вас. Ответ {before + 1}."],
        )
        self.assertEqual(third["reply"], f"Понял вас. Ответ {before + 2}.")
        self.assertNotEqual(third["reply"], target["turns"][0]["reply"])
        ids = [turn["request_id"] for turn in target["turns"]]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(len({turn["conversation_id"] for turn in target["turns"]}), 1)

        expected = {"conversation": 0, "automotive": 0}
        for case in dataset["cases"]:
            for turn in case["turns"]:
                expected[turn["kind"]] += 1
        summary = packet["summary"]["by_kind"]
        self.assertEqual(summary["conversation"]["sent"], expected["conversation"])
        self.assertEqual(summary["automotive"]["sent"], expected["automotive"])
        self.assertGreater(summary["conversation"]["sent"], 0)
        self.assertGreater(summary["automotive"]["sent"], 0)
        self.assertEqual(summary["conversation"]["errors"], 0)
        self.assertEqual(summary["automotive"]["fact_conflicts"], 0)
        self.assertFalse(packet["cases"][0]["turns"][0]["fact_conflicts"])

    def test_harness_records_error_latency_and_stops_without_inventing_reply(self) -> None:
        def respond(raw: bytes, index: int) -> tuple[int, dict]:
            payload = json.loads(raw.decode("utf-8"))
            if index == 0:
                return 200, {
                    "request_id": payload["request_id"],
                    "conversation_id": payload["conversation_id"],
                    "message": {"role": "assistant", "text": "Первый ответ stub."},
                    "metrics": {"elapsed_ms": 0},
                }
            return 502, {
                "request_id": payload["request_id"],
                "conversation_id": payload["conversation_id"],
                "error": {
                    "code": "PROVIDER_UNAVAILABLE",
                    "message": "The local model could not complete the request.",
                },
            }

        stub = StubChat(respond, delay=0.08)
        case = fixture(["раз", "два", "три"])
        try:
            result = run_eval.run_case(case, run_eval.make_http_post(stub.base_url), 5, {
                "expect_cyrillic": True,
                "price_amount_is_failure": True,
                "confirmed_booking_is_failure": True,
                "asserted_hours_is_failure": True,
            })
        finally:
            stub.close()

        self.assertEqual(len(stub.requests), 2)
        self.assertGreaterEqual(result["turns"][0]["latency_ms"], 50)
        self.assertEqual(result["turns"][0]["server_elapsed_ms"], 0)
        self.assertEqual(result["turns"][0]["reply"], "Первый ответ stub.")
        self.assertEqual(result["turns"][1]["error"]["code"], "PROVIDER_UNAVAILABLE")
        self.assertIsNone(result["turns"][1]["reply"])
        self.assertGreaterEqual(result["turns"][1]["latency_ms"], 50)
        second = json.loads(stub.requests[1]["body"].decode("utf-8"))
        self.assertEqual(second["messages"][1], {"role": "assistant", "text": "Первый ответ stub."})
        self.assertNotIn(run_eval.GRADING_CANARY, stub.requests[1]["body"].decode("utf-8"))
        self.assertFalse(result["turns"][2]["sent"])
        self.assertEqual(result["turns"][2]["error"]["code"], "NOT_SENT")
        self.assertIsNone(result["turns"][2]["reply"])

    def test_harness_fact_screens_are_not_wording_scores(self) -> None:
        samples = [
            ("Это стоит 4500 руб.", ["price_amount"]),
            ("Цену нужно уточнить в сервисе.", []),
            ("Обойдётся примерно 2300 ₽.", ["price_amount"]),
            ("Понял, Solaris 2018, часов на 10.", []),
            ("Вы записаны на субботу.", ["confirmed_booking_phrase"]),
            ("Не могу сказать, что вы записаны.", []),
            ("Вы не записаны.", []),
            ("Работаем с 9 до 18.", ["asserted_hours_phrase"]),
            ("Часы работы нужно уточнить в сервисе.", []),
            ("Sure, no problem.", ["missing_cyrillic"]),
            ("Здравствуйте, слушаю вас.", []),
            ("Хорошо, без цифр и без записи.", []),
        ]
        facts = {
            "expect_cyrillic": True,
            "price_amount_is_failure": True,
            "confirmed_booking_is_failure": True,
            "asserted_hours_is_failure": True,
        }
        for text, expected in samples:
            with self.subTest(text=text):
                captured = {}

                def respond(raw: bytes, index: int, reply=text) -> tuple[int, dict]:
                    payload = json.loads(raw.decode("utf-8"))
                    captured["body"] = json.loads(raw.decode("utf-8"))
                    return 200, {
                        "request_id": payload["request_id"],
                        "conversation_id": payload["conversation_id"],
                        "message": {"role": "assistant", "text": reply},
                        "metrics": {"elapsed_ms": 1},
                    }

                stub = StubChat(respond)
                try:
                    result = run_eval.run_case(
                        fixture(["клиент написал"]),
                        run_eval.make_http_post(stub.base_url),
                        5,
                        facts,
                    )
                finally:
                    stub.close()
                self.assertEqual(result["turns"][0]["reply"], text)
                self.assertEqual(result["turns"][0]["fact_conflicts"], expected)
                self.assertNotIn("quality_score", result["turns"][0])
                self.assertNotIn(run_eval.GRADING_CANARY, json.dumps(captured["body"], ensure_ascii=False))

    def test_harness_cli_summary_omits_customer_text(self) -> None:
        dataset = run_eval.load_dataset()
        stub = StubChat(ok_reply)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "packet.json"
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(Path(run_eval.__file__).resolve()),
                        "--base-url",
                        stub.base_url,
                        "--label",
                        "harness-test",
                        "--output",
                        str(output),
                        "--timeout",
                        "5",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("HARNESS TEST", completed.stdout)
                self.assertIn("run_label=harness-test", completed.stdout)
                for case in dataset["cases"]:
                    for turn in case["turns"]:
                        self.assertNotIn(turn["customer"], completed.stdout)
                        self.assertNotIn(turn["customer"], completed.stderr)
                packet = json.loads(output.read_text(encoding="utf-8"))
                self.assertTrue(packet["harness_test"])
                self.assertNotIn("grading_canary", packet)
        finally:
            stub.close()


if __name__ == "__main__":
    print(BANNER)
    unittest.main(verbosity=1)
