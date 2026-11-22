"""Start the local Mica, Qwen, and Bekir UI preview until Ctrl+C."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen


HERE = Path(__file__).resolve().parent
UI = HERE.parent
MICA_BASE = HERE / "models/mica/mica-v0.1-4b-Q4_K_M.gguf"
MICA_LORA = HERE / "mica_baseline_lora.gguf"
QWEN_BASE = HERE / "qwen_project/models/qwen3.5-0.8b/model.safetensors-00001-of-00001.safetensors"


def available(url: str) -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def main() -> int:
    if all(available(url) for url in (
        "http://127.0.0.1:8766/api/health", "http://127.0.0.1:8767/health",
        "http://127.0.0.1:8768/health",
    )):
        print("Preview already running: http://127.0.0.1:8766")
        return 0
    required = [MICA_BASE, MICA_LORA, QWEN_BASE]
    missing = [str(path) for path in required if not path.exists()]
    llama = shutil.which("llama-server")
    if missing or not llama:
        print("Missing local runtime files:", *missing, sep="\n", file=sys.stderr)
        if not llama:
            print("llama-server is not on PATH", file=sys.stderr)
        return 1
    logs = HERE / "logs"
    logs.mkdir(exist_ok=True)
    children = []
    log_files = []
    hidden = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    def launch(name: str, args: list[str], cwd: Path, env: dict[str, str]) -> None:
        log_file = (logs / f"{name}.log").open("w", encoding="utf-8")
        log_files.append(log_file)
        children.append(subprocess.Popen(args, cwd=cwd, env=env, stdout=log_file,
                                         stderr=subprocess.STDOUT, creationflags=hidden))

    try:
        if not available("http://127.0.0.1:8768/health"):
            launch("mica", [llama, "-m", str(MICA_BASE), "--lora", str(MICA_LORA),
                            "--host", "127.0.0.1", "--port", "8768", "-c", "3072",
                            "-ngl", "0", "-t", "6"], HERE, os.environ.copy())
        qwen_env = os.environ.copy()
        qwen_env["HF_HUB_OFFLINE"] = "1"
        qwen_env["PYTHONIOENCODING"] = "utf-8"
        if not available("http://127.0.0.1:8767/health"):
            launch("qwen", [sys.executable, "-B", str(HERE / "serve_models.py")], HERE, qwen_env)
        ui_env = os.environ.copy()
        ui_env["AUTOSERVICE_MODEL_URL"] = "http://127.0.0.1:8767/extract"
        ui_env["PYTHONIOENCODING"] = "utf-8"
        if not available("http://127.0.0.1:8766/api/health"):
            launch("ui", [sys.executable, "-B", "-m", "webapp.server"], UI, ui_env)
        for _ in range(60):
            if all(available(url) for url in (
                "http://127.0.0.1:8768/health", "http://127.0.0.1:8767/health",
                "http://127.0.0.1:8766/api/health",
            )):
                print("Preview ready: http://127.0.0.1:8766", flush=True)
                print("Press Ctrl+C to stop all services.", flush=True)
                break
            if any(child.poll() is not None for child in children):
                raise RuntimeError(f"Service stopped. Read logs in {logs}")
            time.sleep(1)
        else:
            raise TimeoutError(f"Services did not become ready. Read logs in {logs}")
        while True:
            if any(child.poll() is not None for child in children):
                raise RuntimeError(f"Service stopped. Read logs in {logs}")
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        for log_file in log_files:
            log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
