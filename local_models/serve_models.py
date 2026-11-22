"""Serve the bundled trained adapters to the local chat preview."""

from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.request import Request, urlopen

from jinja2 import Environment

from qwen_project.qwen_slot_extractor import QwenSlotExtractor


HOST = "127.0.0.1"
PORT = 8767
MAX_BODY_BYTES = 128 * 1024
ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
sys.path.insert(0, str(RUNTIME))

import prepare_openjev as data
from mica.codebook import OPTION_LABELS
from mica.native import prompt_for
from test_mica_pilot import CatalogSearch, make_queries


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

    def predict(self, history: list[dict[str, str]]) -> dict[str, str]:
        context = "\n".join(
            f"{turn['message_id']} | {'Клиент' if turn['role'] == 'user' else 'Помощник'}: {turn['text']}"
            for turn in history
        )
        shortlist = self.search.shortlist(context, 16)
        queries = make_queries({"history": context}, self.fields, shortlist, self.titles)
        proposals = {}
        for query in queries:
            prompt = prompt_for(query, self.tokenizer)
            payload = json.dumps({"prompt": prompt, "n_predict": 1,
                                  "temperature": 0, "cache_prompt": True}).encode("utf-8")
            request = Request("http://127.0.0.1:8768/completion", payload,
                              {"Content-Type": "application/json; charset=utf-8"})
            with urlopen(request, timeout=120) as response:
                answer = json.load(response).get("content", "").strip()
            label = re.match(r"^[A-Z]$", answer)
            if not label or answer not in OPTION_LABELS[:len(query["candidates"])]:
                raise ValueError(f"Mica did not return a valid label for {query['id']}: {answer!r}")
            choice = query["candidates"][OPTION_LABELS.index(answer)]["id"]
            if choice != "__not_provided__":
                proposals[query["id"]] = choice
        return proposals


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
    extractor = QwenSlotExtractor(project_root=ROOT / "qwen_project", device="cpu")
    mica = MicaProposals()
    model_lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/extract":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY_BYTES:
                    raise ValueError("invalid request length")
                payload = json.loads(self.rfile.read(length))
                history = history_from_messages(payload.get("messages"))
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                self.respond(400, {"error": str(exc)})
                return
            try:
                with model_lock:
                    proposals = mica.predict(history)
                    result = extractor.generate(
                        history, max_new_tokens=768,
                        classifier_proposals=json.dumps(proposals, ensure_ascii=False),
                    )
                if result.value is None or result.errors:
                    self.respond(502, {"error": "invalid model output", "details": result.errors})
                    return
                self.respond(200, result.value)
            except Exception as exc:
                self.respond(500, {"error": type(exc).__name__, "details": str(exc)})

        def do_GET(self) -> None:
            if self.path == "/health":
                self.respond(200, {"status": "ok", "model": "Mica + Qwen local preview"})
            else:
                self.send_error(404)

        def respond(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Mica + Qwen local service: http://{HOST}:{PORT}/extract", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
