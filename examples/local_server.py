#!/usr/bin/env python3
"""Yerel deneme sayfası: python examples/local_server.py"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from connector import YandexLLMClient
from connector.exceptions import YandexLLMError

HOST = "127.0.0.1"
PORT = 8765
ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Yandex LLM Connector</title>
  <style>
    :root { color-scheme: light; }
    body { font-family: system-ui, sans-serif; margin: 0; background: #f4f6f8; color: #1c1c1c; }
    main { max-width: 720px; margin: 40px auto; padding: 0 16px 48px; }
    h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
    p { color: #555; }
    form, #out { background: #fff; border: 1px solid #e2e6ea; border-radius: 12px; padding: 16px; }
    textarea { width: 100%; min-height: 120px; box-sizing: border-box; font: inherit; padding: 10px; border-radius: 8px; border: 1px solid #ccc; }
    button { margin-top: 12px; font: inherit; padding: 8px 16px; border: 0; border-radius: 8px; background: #111; color: #fff; cursor: pointer; }
    button:disabled { opacity: 0.6; cursor: wait; }
    #out { margin-top: 16px; white-space: pre-wrap; }
    .err { color: #9b1c1c; }
  </style>
</head>
<body>
  <main>
    <h1>Yandex LLM Connector</h1>
    <p>Yerel deneme sayfası. İstek, YandexGPT Foundation Models API üzerinden gider.</p>
    <form id="form">
      <textarea id="prompt" placeholder="Bir soru yazın">Merhaba. Tek cümleyle kendini tanıt.</textarea>
      <button type="submit">Gönder</button>
    </form>
    <div id="out">Yanıt burada görünecek.</div>
  </main>
  <script>
    const form = document.getElementById("form");
    const prompt = document.getElementById("prompt");
    const out = document.getElementById("out");
    const button = form.querySelector("button");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      button.disabled = true;
      out.className = "";
      out.textContent = "Bekleniyor…";
      try {
        const response = await fetch("/api/complete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: prompt.value }),
        });
        const data = await response.json();
        if (!response.ok) {
          out.className = "err";
          out.textContent = data.error || "İstek başarısız.";
          return;
        }
        out.textContent = data.text;
      } catch (error) {
        out.className = "err";
        out.textContent = String(error);
      } finally {
        button.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
            return
        self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/complete":
            self._send(404, "application/json", b'{"error":"not found"}')
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                self._json(400, {"error": "prompt boş olamaz"})
                return
            client = YandexLLMClient.from_env()
            try:
                result = client.complete(prompt, max_tokens=500)
            finally:
                client.close()
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        except YandexLLMError as exc:
            self._json(502, {"error": str(exc)})
            return
        except (json.JSONDecodeError, UnicodeError):
            self._json(400, {"error": "geçersiz JSON"})
            return

        self._json(200, {"text": result.text})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _json(self, status: int, data: dict[str, str]) -> None:
        self._send(status, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    load_dotenv(ROOT / ".env")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
