"""Serve the bundled trained adapters to the local chat preview.

Mica is called through llama.cpp. Qwen3.5 uses PyTorch and prefers MPS on
Apple Silicon. A client that hangs up does not keep the model lock.
"""

from __future__ import annotations

import json
import os
import re
import select
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.request import Request, urlopen

from jinja2 import Environment

from qwen_project.qwen_slot_extractor import QwenSlotExtractor


HOST = "127.0.0.1"
PORT = int(os.environ.get("AUTOSERVICE_EXTRACT_PORT", "8767"))
MICA_URL = os.environ.get("AUTOSERVICE_MICA_URL", "http://127.0.0.1:8768/completion")
MAX_BODY_BYTES = 128 * 1024
ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
sys.path.insert(0, str(RUNTIME))

import prepare_openjev as data
from mica.codebook import OPTION_LABELS
from mica.native import prompt_for
from test_mica_pilot import CatalogSearch, make_queries


class ClientClosed(Exception):
    """The extract client went away while inference was still running."""


def peer_closed(connection: socket.socket) -> bool:
    try:
        readable, _, _ = select.select([connection], [], [], 0)
    except (OSError, ValueError):
        return True
    if not readable:
        return False
    try:
        data = connection.recv(1, socket.MSG_PEEK)
    except (BlockingIOError, InterruptedError):
        return False
    except OSError:
        return True
    return data == b""


def post_json(url: str, payload: dict, timeout: float, should_stop) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, body, {"Content-Type": "application/json; charset=utf-8"})
    box: dict = {}

    def run() -> None:
        try:
            with urlopen(request, timeout=timeout) as response:
                box["body"] = json.load(response)
        except Exception as exc:
            box["error"] = exc

    worker = Thread(target=run, daemon=True)
    worker.start()
    started = time.monotonic()
    while worker.is_alive():
        worker.join(0.2)
        if should_stop():
            raise ClientClosed()
        if time.monotonic() - started > timeout:
            raise TimeoutError(url)
    if "error" in box:
        raise box["error"]
    if not isinstance(box.get("body"), dict):
        raise ValueError(f"model response was not an object: {url}")
    return box["body"]


class MicaProposals:
    def __init__(self) -> None:
        _, schema, _, services = data.load_schema(RUNTIME)
        self.fields = {field: schema[field] for field in data.TARGET_FIELDS}
        self.search = CatalogSearch(list(services.values()))
        self.titles = {key: item["source_title"] for key, item in services.items()}
        template = Environment().from_string(
            (ROOT / "mica_tokenizer" / "chat_template.jinja")
            .read_text(encoding="utf-8")
        )

        class ChatTemplate:
            def apply_chat_template(self, messages, **options):
                return template.render(messages=messages, tools=None, add_vision_id=False, **options)

        self.tokenizer = ChatTemplate()

    def predict(self, history: list[dict[str, str]], should_stop=None) -> tuple[dict[str, str], dict[str, float]]:
        context = "\n".join(
            f"{turn['message_id']} | {'Клиент' if turn['role'] == 'user' else 'Помощник'}: {turn['text']}"
            for turn in history
        )
        short_started = time.perf_counter()
        shortlist = self.search.shortlist(context, 16)
        shortlist_ms = (time.perf_counter() - short_started) * 1000
        queries = make_queries({"history": context}, self.fields, shortlist, self.titles)
        proposals = {}
        stop = should_stop or (lambda: False)
        mica_started = time.perf_counter()
        for query in queries:
            if stop():
                raise ClientClosed()
            prompt = prompt_for(query, self.tokenizer)
            answer = post_json(
                MICA_URL,
                {"prompt": prompt, "n_predict": 1, "temperature": 0, "cache_prompt": True},
                120,
                stop,
            ).get("content", "").strip()
            label = re.match(r"^[A-Z]$", answer)
            if not label or answer not in OPTION_LABELS[:len(query["candidates"])]:
                raise ValueError(f"Mica did not return a valid label for {query['id']}: {answer!r}")
            choice = query["candidates"][OPTION_LABELS.index(answer)]["id"]
            if choice != "__not_provided__":
                proposals[query["id"]] = choice
        mica_ms = (time.perf_counter() - mica_started) * 1000
        return proposals, {
            "catalog_shortlist_ms": round(shortlist_ms, 1),
            "mica_ms": round(mica_ms, 1),
        }


def history_from_messages(messages: object) -> list[dict[str, str]]:
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a nonempty list")
    history = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("each message must be an object")
        role, content = message.get("role"), message.get("text")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            raise ValueError("each message needs role and text")
        if role == "assistant":
            try:
                prior = json.loads(content)
            except ValueError:
                prior = None
            if isinstance(prior, dict) and {"slots_after_message", "evidence"} <= prior.keys():
                continue
        history.append({"message_id": f"m{len(history) + 1}", "role": role, "text": content})
    if history[-1]["role"] != "user":
        raise ValueError("the final message must be from the user")
    return history


def main() -> None:
    extractor = QwenSlotExtractor(project_root=ROOT / "qwen_project", device="auto")
    mica = MicaProposals()
    model_lock = Lock()
    print(f"Qwen device: {extractor.device}", flush=True)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path not in {"/extract", "/draft"}:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY_BYTES:
                    raise ValueError("invalid request length")
                payload = json.loads(self.rfile.read(length))
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                self.respond(400, {"error": str(exc)})
                return
            if self.path == "/draft":
                transcript = payload.get("transcript") if isinstance(payload, dict) else None
                try:
                    with model_lock:
                        if peer_closed(self.connection):
                            raise ClientClosed()
                        text, seconds, count = extractor.draft_reply(transcript)
                    self.respond(200, {"text": text, "seconds": round(seconds, 3), "tokens": count})
                except ClientClosed:
                    self.close_connection = True
                except (RuntimeError, ValueError) as exc:
                    self.respond(502, {"error": str(exc)})
                return
            try:
                history = history_from_messages(payload.get("messages"))
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                self.respond(400, {"error": str(exc)})
                return
            should_stop = lambda: peer_closed(self.connection)
            try:
                with model_lock:
                    if should_stop():
                        raise ClientClosed()
                    proposals, mica_stages = mica.predict(history, should_stop)
                    qwen_started = time.perf_counter()
                    result = extractor.generate(
                        history, max_new_tokens=768,
                        classifier_proposals=json.dumps(proposals, ensure_ascii=False),
                        should_stop=should_stop,
                    )
                    qwen_ms = round((time.perf_counter() - qwen_started) * 1000, 1)
                    if result.errors == ["cancelled"] or should_stop():
                        raise ClientClosed()
                if result.value is None or result.errors:
                    self.respond(502, {"error": "invalid model output", "details": result.errors})
                    return
                payload = dict(result.value)
                payload["stage_ms"] = {
                    "catalog_shortlist_ms": mica_stages["catalog_shortlist_ms"],
                    "mica_ms": mica_stages["mica_ms"],
                    "qwen_ms": qwen_ms,
                }
                self.respond(200, payload)
            except ClientClosed:
                self.close_connection = True
                return
            except Exception as exc:
                self.respond(500, {"error": type(exc).__name__, "details": str(exc)})

        def do_GET(self) -> None:
            if self.path == "/health":
                self.respond(200, {
                    "status": "ok",
                    "model": "Mica + Qwen local preview",
                    "qwen_device": str(extractor.device),
                })
            else:
                self.send_error(404)

        def respond(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Mica + Qwen local service: http://{HOST}:{PORT}/extract", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
