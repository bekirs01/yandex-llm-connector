"""Download the public base weights required by the bundled trained adapters."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parent
MICA_REVISION = "ca36594cc2067c7252704f9f304cc10ef11c7c5c"
QWEN_REVISION = "2fc06364715b967f1860aea9cf38778875588b17"
QWEN_SHA256 = "04b1c301231dd422b8860db31311ab2721511346a32cb1e079c4c4e5f1fe4696"
MICA_BYTES = 3_066_384_768


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl is required to download the public base models")
    mica_dir = ROOT / "models/mica"
    qwen_dir = ROOT / "qwen_project/models/qwen3.5-0.8b"
    mica_dir.mkdir(parents=True, exist_ok=True)
    qwen_dir.mkdir(parents=True, exist_ok=True)
    mica = mica_dir / "mica-v0.1-4b-Q4_K_M.gguf"
    if not mica.is_file() or mica.stat().st_size != MICA_BYTES:
        print("Downloading Mica Q4 base model (about 3 GB)...", flush=True)
        subprocess.run([curl, "--location", "--fail", "--retry", "3", "-C", "-",
                        "--output", str(mica),
                        f"https://huggingface.co/sky7350/Mica-v0.1-4B/resolve/{MICA_REVISION}/{mica.name}"],
                       check=True)
    qwen = qwen_dir / "model.safetensors-00001-of-00001.safetensors"
    if not qwen.is_file() or sha256(qwen) != QWEN_SHA256:
        print("Downloading Qwen base model (about 1.75 GB)...", flush=True)
        subprocess.run([curl, "--location", "--fail", "--retry", "3", "-C", "-",
                        "--output", str(qwen),
                        f"https://huggingface.co/Qwen/Qwen3.5-0.8B/resolve/{QWEN_REVISION}/{qwen.name}"],
                       check=True)
    if sha256(qwen) != QWEN_SHA256:
        raise ValueError("Qwen base weight SHA-256 mismatch")
    if not mica.is_file() or mica.stat().st_size != MICA_BYTES:
        raise ValueError("Mica base model download is incomplete")
    print("Base models ready. Run local_models/start_preview.py", flush=True)


if __name__ == "__main__":
    main()
