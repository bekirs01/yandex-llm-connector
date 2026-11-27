"""Localhost HTTP server for the automotive-service chat preview.

Run from the repository root:

    python -m webapp.server
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from data_layer.customer_questions import (
    CustomerQuestionError,
    locate_exchange,
    read_panel_revision,
    read_question_tree,
)
from data_layer.exchange_feedback import (
    ExchangeFeedbackError,
    parse_save_payload,
    read_feedback,
    save_feedback,
)
from data_layer.quality_review import (
    QualityReviewError,
    export_approved_jsonl,
    list_quality,
    parse_decision_payload,
    save_decision,
)
from webapp.chat_service import ChatService, error_response

HOST = "127.0.0.1"
DEFAULT_PORT = 8766
MAX_BODY_BYTES = 128 * 1024
REQUEST_READ_TIMEOUT_SECONDS = 10.0

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = REPO_ROOT / "web"

_DOTENV_KEYS = frozenset(
    {
        "YANDEX_CLOUD_FOLDER_ID",
        "YANDEX_CLOUD_API_KEY",
        "YANDEX_IAM_TOKEN",
        "YANDEX_GPT_MODEL",
    }
)
_ALLOWED_SUFFIXES = frozenset(
    {
        ".html",
        ".css",
        ".js",
        ".mjs",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".map",
        ".json",
        ".txt",
        ".webmanifest",
    }
)
_SAFE_TREE_ERROR = re.compile(
    r"^(?:invalid [a-z_]+|unknown node|question tree database call failed)$"
)
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".map": "application/json",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".webmanifest": "application/manifest+json",
}


class LocalChatHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def load_dotenv(path: Path) -> None:
    """Load connector settings from a .env file without executing it as shell.

    Values already present in the process environment are left unchanged.
    Only the connector's own variable names are applied.
    """

    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in _DOTENV_KEYS:
            continue
        cleaned = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, cleaned)


def resolve_static_file(url_path: str, web_root: Path) -> Path | None:
    """Resolve a URL path to a file inside web_root, or return None.

    Symlinks and path segments that escape web_root are rejected. Hidden files,
    directory listings, and non-frontend suffixes are not served.
    """

    if not url_path.startswith("/") or url_path.startswith("//"):
        return None
    decoded = urllib.parse.unquote(url_path)
    if not decoded.startswith("/") or decoded.startswith("//"):
        return None
    if any(char in decoded for char in "\x00\r\n\\"):
        return None

    relative = "index.html" if decoded == "/" else decoded.lstrip("/")
    if relative.startswith("/") or relative == "":
        return None
    parts = Path(relative).parts
    if not parts or any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
        return None
    if Path(parts[-1]).suffix.lower() not in _ALLOWED_SUFFIXES:
        return None

    root = web_root.resolve()
    current = root
    for part in parts:
        if not current.is_dir():
            return None
        current = current / part
        if _escapes_root(current, root):
            return None
    if not current.is_file() or current.resolve().suffix.lower() not in _ALLOWED_SUFFIXES:
        return None
    if _escapes_root(current, root):
        return None
    return current.resolve()


def _escapes_root(path: Path, root: Path) -> bool:
    try:
        if path.is_symlink() or path.exists():
            return not path.resolve().is_relative_to(root)
    except OSError:
        return True
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Localhost chat preview server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port bound to 127.0.0.1")
    return parser


def validate_port(port: int) -> None:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SystemExit("error: port must be between 1 and 65535")


def create_server(
    service: ChatService,
    port: int,
    web_root: Path | None = None,
    read_timeout: float = REQUEST_READ_TIMEOUT_SECONDS,
) -> LocalChatHTTPServer:
    root = WEB_ROOT if web_root is None else web_root
    handler = _build_handler(service, root, read_timeout)
    return LocalChatHTTPServer((HOST, port), handler)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    validate_port(args.port)
    load_dotenv(REPO_ROOT / ".env")
    server = create_server(ChatService(), args.port)
    print(f"http://{HOST}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return
    finally:
        server.server_close()


def _build_handler(
    service: ChatService,
    web_root: Path,
    read_timeout: float,
) -> type[BaseHTTPRequestHandler]:
    class ChatRequestHandler(BaseHTTPRequestHandler):
        server_service = service
        server_web_root = web_root
        server_read_timeout = read_timeout

        def do_GET(self) -> None:
            self._dispatch(self._handle_get)

        def do_POST(self) -> None:
            self._dispatch(self._handle_post)

        def log_message(self, fmt: str, *args: object) -> None:
            sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

        def _dispatch(self, method: Callable[[], None]) -> None:
            try:
                method()
            except Exception as exc:
                sys.stderr.write(f"chat http error: {type(exc).__name__}\n")
                if not getattr(self, "_responded", False):
                    self._send_bytes(500, "text/plain; charset=utf-8", b"Internal server error\n")

        def _handle_get(self) -> None:
            path = _url_path(self.path)
            if path == "/api/health":
                self._send_json(200, self.server_service.health())
                return
            if path == "/api/question-tree":
                self._send_question_tree(self.path)
                return
            if path == "/api/question-tree-locate":
                self._send_question_tree_locate(self.path)
                return
            if path == "/api/panel-revision":
                self._send_panel_revision()
                return
            if path == "/api/quality-review/export":
                self._send_quality_export()
                return
            if path == "/api/quality-review":
                self._send_quality_read(self.path)
                return
            if path == "/api/feedback":
                self._send_feedback_read(self.path)
                return
            if path == "/api/chat":
                self._send_bytes(405, "text/plain; charset=utf-8", b"Method not allowed\n")
                return
            if path.startswith("/api/"):
                self._send_bytes(404, "text/plain; charset=utf-8", b"Not found\n")
                return
            file_path = resolve_static_file(path, self.server_web_root)
            if file_path is None:
                self._send_bytes(404, "text/plain; charset=utf-8", b"Not found\n")
                return
            try:
                body = file_path.read_bytes()
            except OSError:
                self._send_bytes(404, "text/plain; charset=utf-8", b"Not found\n")
                return
            content_type = _CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
            self._send_bytes(200, content_type, body)

        def _handle_post(self) -> None:
            path = _url_path(self.path)
            if path in {"/api/question-tree", "/api/question-tree-locate", "/api/panel-revision"}:
                self._send_bytes(405, "text/plain; charset=utf-8", b"Method not allowed\n")
                return
            if path == "/api/quality-review/export":
                self._send_bytes(405, "text/plain; charset=utf-8", b"Method not allowed\n")
                return
            if path == "/api/quality-review":
                self._send_quality_write()
                return
            if path == "/api/feedback":
                self._send_feedback_write()
                return
            if path != "/api/chat":
                status = 405 if path == "/api/health" else 404
                message = b"Method not allowed\n" if status == 405 else b"Not found\n"
                self._send_bytes(status, "text/plain; charset=utf-8", message)
                return

            length = self._declared_length()
            if length is None:
                return
            if not _is_json_content_type(self.headers.get("Content-Type")):
                self._send_json(
                    400,
                    error_response(None, None, "INVALID_REQUEST", "Content-Type must be application/json."),
                )
                return
            body = self._read_body(length)
            if body is None:
                return
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(
                    400,
                    error_response(None, None, "INVALID_REQUEST", "Request body must be valid UTF-8 JSON."),
                )
                return
            status, response = self.server_service.handle_chat(payload)
            self._send_json(status, response)

        def _declared_length(self) -> int | None:
            if self.headers.get("Transfer-Encoding"):
                self._reject_request("Chunked transfer encoding is not supported.")
                return None
            values = self.headers.get_all("Content-Length")
            if not values or len(values) != 1:
                self._reject_request("Content-Length is required.")
                return None
            try:
                length = int(values[0].strip())
            except ValueError:
                self._reject_request("Content-Length is invalid.")
                return None
            if length < 0 or length > MAX_BODY_BYTES:
                self.close_connection = True
                self._reject_request("Request body exceeds 128 KiB.")
                return None
            return length

        def _read_body(self, length: int) -> bytes | None:
            if length == 0:
                return b""
            self.connection.settimeout(self.server_read_timeout)
            try:
                body = _read_exact(self.rfile.read, length)
            except TimeoutError:
                self.close_connection = True
                self._reject_request("Timed out while reading the request body.")
                return None
            finally:
                try:
                    self.connection.settimeout(None)
                except OSError:
                    pass
            if body is None:
                self._reject_request("Request body ended early.")
                return None
            return body

        def _reject_request(self, message: str) -> None:
            self._send_json(400, error_response(None, None, "INVALID_REQUEST", message))

        def _send_feedback_read(self, raw_path: str) -> None:
            try:
                arguments = _feedback_query(raw_path)
                payload = read_feedback(arguments["conversation_id"], arguments["request_id"])
            except ExchangeFeedbackError as exc:
                status, body = _feedback_error(exc)
                self._send_json(status, body)
                return
            self._send_json(200, payload)

        def _send_feedback_write(self) -> None:
            length = self._declared_length()
            if length is None:
                return
            if not _is_json_content_type(self.headers.get("Content-Type")):
                self._send_json(400, _feedback_error(ExchangeFeedbackError("invalid request"))[1])
                return
            body = self._read_body(length)
            if body is None:
                return
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, _feedback_error(ExchangeFeedbackError("invalid request"))[1])
                return
            try:
                fields = parse_save_payload(payload)
                saved = save_feedback(
                    fields["conversation_id"],
                    fields["request_id"],
                    fields["stars"],
                    fields["resolved"],
                    fields["revision"],
                )
            except ExchangeFeedbackError as exc:
                status, error_body = _feedback_error(exc)
                self._send_json(status, error_body)
                return
            self._send_json(200, saved)

        def _send_panel_revision(self) -> None:
            try:
                revision = read_panel_revision()
            except CustomerQuestionError:
                self._send_json(503, {
                    "error": {
                        "code": "TREE_UNAVAILABLE",
                        "message": "Не удалось проверить обновление дерева.",
                    }
                })
                return
            self._send_json(200, {"revision": revision})

        def _send_question_tree_locate(self, raw_path: str) -> None:
            try:
                arguments = _locate_arguments(raw_path)
                payload = locate_exchange(
                    arguments["conversation_id"],
                    arguments["request_id"],
                    limit=arguments["limit"],
                )
            except CustomerQuestionError as exc:
                status, body = _locate_error(exc)
                self._send_json(status, body)
                return
            self._send_json(200, payload)

        def _send_quality_read(self, raw_path: str) -> None:
            try:
                arguments = _quality_arguments(raw_path)
                payload = list_quality(
                    arguments["bucket"],
                    limit=arguments["limit"],
                    offset=arguments["offset"],
                )
            except (QualityReviewError, CustomerQuestionError) as exc:
                if isinstance(exc, CustomerQuestionError):
                    reason = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
                    exc = QualityReviewError(
                        "invalid request" if reason.startswith("invalid ")
                        else "quality review database call failed"
                    )
                status, body = _quality_error(exc)
                self._send_json(status, body)
                return
            self._send_json(200, payload)

        def _send_quality_write(self) -> None:
            length = self._declared_length()
            if length is None:
                return
            if not _is_json_content_type(self.headers.get("Content-Type")):
                self._send_json(400, _quality_error(QualityReviewError("invalid request"))[1])
                return
            body = self._read_body(length)
            if body is None:
                return
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, _quality_error(QualityReviewError("invalid request"))[1])
                return
            try:
                fields = parse_decision_payload(payload)
                saved = save_decision(
                    fields["conversation_id"],
                    fields["request_id"],
                    fields["decision"],
                )
            except QualityReviewError as exc:
                status, error_body = _quality_error(exc)
                self._send_json(status, error_body)
                return
            self._send_json(200, saved)

        def _send_quality_export(self) -> None:
            try:
                body, count = export_approved_jsonl()
            except QualityReviewError:
                self._send_json(503, _quality_error(QualityReviewError("quality review database call failed"))[1])
                return
            encoded = body.encode("utf-8")
            self._responded = True
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("X-Export-Count", str(count))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Disposition", 'attachment; filename="approved-examples.jsonl"')
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)

        def _send_question_tree(self, raw_path: str) -> None:
            # The customer chat does not call this route. The process listens on localhost.
            try:
                arguments = _question_tree_arguments(raw_path)
                payload = read_question_tree(
                    arguments["node_id"],
                    view=arguments["view"],
                    limit=arguments["limit"],
                    offset=arguments["offset"],
                )
            except CustomerQuestionError as exc:
                reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "question tree database call failed"
                if _SAFE_TREE_ERROR.fullmatch(reason) is None:
                    reason = "question tree database call failed"
                status = 400 if reason.startswith("invalid ") or reason == "unknown node" else 500
                self._send_json(status, {"error": reason})
                return
            self._send_json(200, payload)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(status, "application/json; charset=utf-8", body)

        def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
            self._responded = True
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

    return ChatRequestHandler


def _feedback_query(raw_path: str) -> dict[str, str]:
    parsed = urllib.parse.urlsplit(raw_path)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if set(params) - {"conversation_id", "request_id"}:
        raise ExchangeFeedbackError("invalid request")
    conversation_id = _one_feedback_value(params, "conversation_id")
    request_id = _one_feedback_value(params, "request_id")
    if conversation_id is None:
        raise ExchangeFeedbackError("invalid conversation_id")
    if request_id is None:
        raise ExchangeFeedbackError("invalid request_id")
    return {"conversation_id": conversation_id, "request_id": request_id}


def _one_feedback_value(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values or len(values) != 1:
        return None
    text = values[0].strip()
    return text or None


def _feedback_error(exc: ExchangeFeedbackError) -> tuple[int, dict[str, Any]]:
    reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "exchange feedback database call failed"
    if reason == "unknown exchange":
        return 404, {
            "error": {
                "code": "UNKNOWN_EXCHANGE",
                "message": "Оценка не сохранена: этот ответ не найден.",
            }
        }
    if reason.startswith("invalid "):
        return 400, {
            "error": {
                "code": "INVALID_REQUEST",
                "message": "Некорректная оценка.",
            }
        }
    return 503, {
        "error": {
            "code": "FEEDBACK_UNAVAILABLE",
            "message": "Оценка не сохранена.",
        }
    }


def _locate_arguments(raw_path: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(raw_path)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if set(params) - {"conversation_id", "request_id", "limit"}:
        raise CustomerQuestionError("invalid request")
    conversation_id = _optional_query_text(params, "conversation_id")
    request_id = _optional_query_text(params, "request_id")
    if not conversation_id:
        raise CustomerQuestionError("invalid conversation_id")
    if not request_id:
        raise CustomerQuestionError("invalid request_id")
    return {
        "conversation_id": conversation_id,
        "request_id": request_id,
        "limit": _query_int(params, "limit", default=20),
    }


def _locate_error(exc: CustomerQuestionError) -> tuple[int, dict[str, Any]]:
    reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "question tree database call failed"
    if reason == "unknown exchange":
        return 404, {
            "error": {
                "code": "UNKNOWN_EXCHANGE",
                "message": "Такой обмен не найден.",
            }
        }
    if reason.startswith("invalid "):
        return 400, {
            "error": {
                "code": "INVALID_REQUEST",
                "message": "Некорректная ссылка на обмен.",
            }
        }
    return 503, {
        "error": {
            "code": "TREE_UNAVAILABLE",
            "message": "Не удалось открыть этот обмен.",
        }
    }


def _quality_arguments(raw_path: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(raw_path)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if set(params) - {"bucket", "limit", "offset"}:
        raise QualityReviewError("invalid request")
    bucket = _optional_query_text(params, "bucket") or "positive"
    return {
        "bucket": bucket,
        "limit": _query_int(params, "limit", default=20),
        "offset": _query_int(params, "offset", default=0),
    }


def _quality_error(exc: QualityReviewError) -> tuple[int, dict[str, Any]]:
    reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "quality review database call failed"
    if reason == "unknown exchange":
        return 404, {
            "error": {
                "code": "UNKNOWN_EXCHANGE",
                "message": "Такой обмен не найден.",
            }
        }
    if reason == "feedback required":
        return 409, {
            "error": {
                "code": "FEEDBACK_REQUIRED",
                "message": "Сначала нужна оценка клиента.",
            }
        }
    if reason.startswith("invalid "):
        return 400, {
            "error": {
                "code": "INVALID_REQUEST",
                "message": "Некорректное решение по примеру.",
            }
        }
    return 503, {
        "error": {
            "code": "QUALITY_UNAVAILABLE",
            "message": "Не удалось прочитать проверку качества.",
        }
    }


def _question_tree_arguments(raw_path: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(raw_path)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    return {
        "node_id": _optional_query_text(params, "node_id"),
        "view": _optional_query_text(params, "view") or "tree",
        "limit": _query_int(params, "limit", default=20),
        "offset": _query_int(params, "offset", default=0),
    }


def _optional_query_text(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    if len(values) != 1:
        raise CustomerQuestionError(f"invalid {name}")
    text = values[0].strip()
    return text or None


def _query_int(params: dict[str, list[str]], name: str, default: int) -> int:
    values = params.get(name)
    if not values:
        return default
    if len(values) != 1 or not re.fullmatch(r"[0-9]{1,9}", values[0].strip()):
        raise CustomerQuestionError(f"invalid {name}")
    return int(values[0].strip())


def _url_path(raw_path: str) -> str:
    parsed = urllib.parse.urlsplit(raw_path)
    if parsed.scheme or parsed.netloc:
        return ""
    path = parsed.path
    if not path.startswith("/"):
        return ""
    return path


def _is_json_content_type(value: str | None) -> bool:
    if not value:
        return False
    media = value.split(";", 1)[0].strip().lower()
    return media == "application/json"


def _read_exact(read: Callable[[int], bytes], length: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = read(min(remaining, 65536))
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


if __name__ == "__main__":
    main()
