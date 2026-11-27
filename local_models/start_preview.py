"""Start the local Mica server, Qwen extractor, and web UI.

Run from the repository root after the virtual environment and model files
are installed. This process stops only the children it started. A port that
is already healthy is reused. A port that is busy but not healthy is left
untouched and the launcher exits.

The project database is started only when this launcher is preparing the
local app. A healthy cluster is reused. HTTP requests do not start it.
"""

from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"


def port_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise SystemExit(f"{name} must be between 1 and 65535")
    return port


UI_PORT = port_from_env("AUTOSERVICE_UI_PORT", 8766)
EXTRACT_PORT = port_from_env("AUTOSERVICE_EXTRACT_PORT", 8767)
MICA_PORT = port_from_env("AUTOSERVICE_MICA_PORT", 8768)
MICA_URL = os.environ.get("AUTOSERVICE_MICA_URL", f"http://{HOST}:{MICA_PORT}/completion")
UI_URL = f"http://{HOST}:{UI_PORT}"
EXTRACT_HEALTH = f"http://{HOST}:{EXTRACT_PORT}/health"
MICA_HEALTH = f"http://{HOST}:{MICA_PORT}/health"
MICA_BASE = ROOT / "local_models" / "models" / "mica" / "mica-v0.1-4b-Q4_K_M.gguf"
MICA_LORA = ROOT / "local_models" / "mica_baseline_lora.gguf"
QWEN_BASE = (
    ROOT / "local_models" / "qwen_project" / "models" / "qwen3.5-0.8b"
    / "model.safetensors-00001-of-00001.safetensors"
)


def mica_gpu_layers() -> str:
    explicit = os.environ.get("AUTOSERVICE_MICA_NGL", "").strip()
    if explicit:
        return explicit
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "all"
    return "0"


LOCAL_PG_SOCKET = "/tmp/autoservice-pg"
LOCAL_PG_PORT = "54332"
LOCAL_PG_DATABASE = "autoservice_assistant"
LOCAL_PG_ROLE = "autoservice_runtime"
LOCAL_PG_DATA = ROOT / ".local_pg" / "data"
LOCAL_PG_LOG = ROOT / ".local_pg" / "postgres.log"
LOCAL_PG_READY_TIMEOUT = 30


def _configured_database() -> tuple[str, str, str]:
    socket_dir = os.environ.get("AUTOSERVICE_LOCAL_PGSOCKET", LOCAL_PG_SOCKET).strip() or LOCAL_PG_SOCKET
    port = os.environ.get("AUTOSERVICE_LOCAL_PGPORT", LOCAL_PG_PORT).strip() or LOCAL_PG_PORT
    database = os.environ.get("AUTOSERVICE_LOCAL_PGDATABASE", LOCAL_PG_DATABASE).strip() or LOCAL_PG_DATABASE
    return socket_dir, port, database


def uses_project_database() -> bool:
    """True when the app is pointed at this checkout's local cluster."""

    return _configured_database() == (LOCAL_PG_SOCKET, LOCAL_PG_PORT, LOCAL_PG_DATABASE)


def _psql_binary() -> str:
    return os.environ.get("AUTOSERVICE_PSQL", "/opt/homebrew/opt/postgresql@18/bin/psql")


def _pg_ctl_binary() -> str | None:
    explicit = os.environ.get("AUTOSERVICE_PG_CTL", "").strip()
    if explicit:
        return explicit
    sibling = Path(_psql_binary()).parent / "pg_ctl"
    if sibling.is_file():
        return str(sibling)
    return shutil.which("pg_ctl")


def database_probe() -> tuple[bool, str]:
    """Return whether the runtime role can read the configured database."""

    socket_dir, port, database = _configured_database()
    try:
        completed = subprocess.run(
            [
                _psql_binary(),
                "-h", socket_dir,
                "-p", port,
                "-U", LOCAL_PG_ROLE,
                "-d", database,
                "-X", "-q", "-t", "-A",
                "-v", "ON_ERROR_STOP=1",
                "-c", "select 1",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if completed.returncode == 0 and completed.stdout.strip() == "1":
        return True, ""
    detail = (completed.stderr or completed.stdout or "").strip()
    return False, detail


def ensure_local_database() -> None:
    """Reuse a healthy local cluster, or start the existing one.

    An explicitly configured socket, port, or database is left alone.
    This does not create a cluster, and it does not run on HTTP requests.
    """

    socket_dir, port, database = _configured_database()
    if not uses_project_database():
        print(
            "Database connection is configured explicitly "
            f"({socket_dir}, port {port}, database {database}). "
            "The project cluster was not started."
        )
        return
    ready, detail = database_probe()
    if ready:
        print(f"Local database is already accepting connections for {LOCAL_PG_ROLE}.")
        return
    socket_path = Path(LOCAL_PG_SOCKET) / f".s.PGSQL.{LOCAL_PG_PORT}"
    if socket_path.exists():
        raise SystemExit(
            "Local PostgreSQL is listening, but "
            f"{LOCAL_PG_ROLE} could not read {LOCAL_PG_DATABASE}. "
            "The launcher did not start another cluster.\n"
            f"{detail}".rstrip()
        )
    if not (LOCAL_PG_DATA / "PG_VERSION").is_file():
        raise SystemExit(
            f"Local database cluster was not found at {LOCAL_PG_DATA}. "
            "This launcher does not create a replacement cluster."
        )
    pg_ctl = _pg_ctl_binary()
    if pg_ctl is None:
        raise SystemExit(
            "pg_ctl was not found. Install PostgreSQL 18 or set AUTOSERVICE_PG_CTL. "
            f"The last connection error was: {detail or 'no response'}"
        )
    socket_dir_path = Path(LOCAL_PG_SOCKET)
    socket_dir_path.mkdir(mode=0o700, exist_ok=True)
    os.chmod(socket_dir_path, 0o700)
    LOCAL_PG_LOG.parent.mkdir(exist_ok=True)
    completed = subprocess.run(
        [
            pg_ctl,
            "-D", str(LOCAL_PG_DATA),
            "-l", str(LOCAL_PG_LOG),
            "-w",
            "-t", str(LOCAL_PG_READY_TIMEOUT),
            "-o", f"-p {LOCAL_PG_PORT} -k {LOCAL_PG_SOCKET} -c listen_addresses=",
            "start",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=LOCAL_PG_READY_TIMEOUT + 15,
        check=False,
    )
    ready, probe_detail = database_probe()
    if ready:
        print(f"Local database is accepting connections for {LOCAL_PG_ROLE}.")
        return
    started = "\n".join(part.strip() for part in (completed.stderr, completed.stdout) if part and part.strip())
    log_tail = ""
    if LOCAL_PG_LOG.is_file():
        log_tail = "\n".join(LOCAL_PG_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-20:])
    raise SystemExit(
        "Local database did not become ready for "
        f"{LOCAL_PG_ROLE} on {LOCAL_PG_SOCKET}:{LOCAL_PG_PORT} "
        f"within {LOCAL_PG_READY_TIMEOUT} seconds.\n"
        f"{started}\n{probe_detail}\n{log_tail}".rstrip()
    )


def healthy(url: str) -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def port_open(port: int) -> bool:
    import socket

    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((HOST, port)) == 0


def require_ready(name: str, port: int, health_url: str) -> str:
    if healthy(health_url):
        print(f"{name} is already running at {health_url}")
        return "ready"
    if port_open(port):
        raise SystemExit(
            f"{name} port {port} is in use, but {health_url} did not answer. "
            f"This launcher will not stop that process. Free the port or set a different one."
        )
    return "start"


def main() -> int:
    missing = [str(path.relative_to(ROOT)) for path in (MICA_BASE, MICA_LORA, QWEN_BASE) if not path.is_file()]
    if missing:
        print("Missing model files:", file=sys.stderr)
        for item in missing:
            print(f"  {item}", file=sys.stderr)
        print("Install the base weights with: python local_models/setup_models.py", file=sys.stderr)
        return 1
    llama = shutil.which("llama-server")
    if llama is None:
        print("llama-server was not found on PATH.", file=sys.stderr)
        print("On Apple Silicon, install a Metal build with: brew install llama.cpp", file=sys.stderr)
        return 1
    try:
        ensure_local_database()
        ui_state = require_ready("web UI", UI_PORT, f"{UI_URL}/api/health")
        extract_state = require_ready("extractor", EXTRACT_PORT, EXTRACT_HEALTH)
        mica_state = require_ready("Mica", MICA_PORT, MICA_HEALTH)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    if ui_state == extract_state == mica_state == "ready":
        print(f"Local chat: {UI_URL}")
        return 0

    qwen_env = os.environ.copy()
    qwen_env["HF_HUB_OFFLINE"] = "1"
    qwen_env["TRANSFORMERS_OFFLINE"] = "1"
    qwen_env["PYTHONIOENCODING"] = "utf-8"
    qwen_env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    qwen_env["AUTOSERVICE_EXTRACT_PORT"] = str(EXTRACT_PORT)
    qwen_env["AUTOSERVICE_MICA_URL"] = MICA_URL
    ui_env = os.environ.copy()
    ui_env["AUTOSERVICE_MODEL_URL"] = f"http://{HOST}:{EXTRACT_PORT}/extract"
    ui_env["PYTHONIOENCODING"] = "utf-8"
    commands = []
    if mica_state == "start":
        commands.append((
            "Mica",
            [llama, "-m", str(MICA_BASE), "--lora", str(MICA_LORA),
             "--host", HOST, "--port", str(MICA_PORT), "-c", "3072",
             "-ngl", mica_gpu_layers(), "-np", "1"],
            os.environ.copy(),
            MICA_HEALTH,
        ))
    if extract_state == "start":
        commands.append((
            "Qwen",
            [sys.executable, "-B", str(ROOT / "local_models" / "serve_models.py")],
            qwen_env,
            EXTRACT_HEALTH,
        ))
    if ui_state == "start":
        commands.append((
            "UI",
            [sys.executable, "-B", "-m", "webapp.server", "--port", str(UI_PORT)],
            ui_env,
            f"{UI_URL}/api/health",
        ))
    children = []
    try:
        for name, command, env, health_url in commands:
            children.append(subprocess.Popen(command, cwd=ROOT, env=env))
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if children[-1].poll() is not None:
                    print(f"{name} exited before it became ready.", file=sys.stderr)
                    return 1
                if healthy(health_url):
                    break
                time.sleep(0.5)
            else:
                print(f"{name} did not become ready at {health_url}.", file=sys.stderr)
                return 1
        print(f"Local chat: {UI_URL}")
        print("Press Ctrl+C to stop the processes started by this command.")
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        print("A local service exited.", file=sys.stderr)
        return 1
    finally:
        for child in children:
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 8
        for child in children:
            remaining = max(0, deadline - time.monotonic())
            try:
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    raise SystemExit(main())
