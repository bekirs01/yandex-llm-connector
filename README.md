# Yandex LLM Connector

Local automotive-service chat for development, plus a small YandexGPT client. The chat runs on your computer. A question goes through a local Mica classifier, a local Qwen slot extractor, and a dialogue policy that writes the Russian reply. Structured slots stay in a developer panel. The browser keeps the conversation history.

This is a development version. The current reply quality is the baseline for this release.

## Main features

- Local web chat on `127.0.0.1`.
- Mica v0.1 4B, Q4_K_M, with the trained LoRA adapter in this repository.
- Qwen3.5 0.8B with the trained LoRA adapter in this repository.
- Dialogue policy that turns extracted slots and evidence into a Russian customer reply.
- Developer panel for the structured extraction.
- Conversation history owned by the browser.
- Optional YandexGPT client for callers that set Yandex Cloud credentials. The local launcher does not use it.

## Current development status

The integrated local path is the supported way to run the chat. A bare greeting such as `привет` or `здравствуйте` returns a fixed Russian introduction and does not call the models. Any other customer message is sent to the local extractor.

Apple Silicon is the tested acceleration path: Mica through llama.cpp Metal, Qwen through PyTorch MPS. Linux and Windows can run the same code on CPU. This repository does not ship or configure a CUDA or ROCm build.

## Supported operating systems

| System | What works |
| --- | --- |
| macOS on Apple Silicon (M1, M2, M3, M4, and newer chips supported by your macOS and PyTorch) | Tested path. Mica uses Metal when `llama-server` is a Metal build. Qwen uses MPS. |
| Intel Mac | The launcher starts Mica on CPU (`-ngl 0`) and Qwen on CPU. Metal and MPS are not used. |
| Linux | CPU path. Install your own `llama-server`. The default PyTorch wheel from `requirements.txt` is the CPU wheel. GPU offload is not set up here. |
| Windows | CPU path. `llama-server` must be on `PATH`. The default PyTorch wheel is the CPU wheel. GPU offload is not set up here. |

## Hardware requirements

- Memory: 24 GB is a comfortable size for the development machine used with these models. 16 GB is tight because the Mica Q4 file is about 3 GB and the Qwen base file is about 1.75 GB, before activations and the operating system.
- Disk: about 5 GB for the two base files, plus the virtual environment. PyTorch is a large wheel. The trained LoRA adapters are already in the git repository and are small.
- Apple Silicon uses unified memory for both Metal and MPS.
- Qwen3.5's fast linear-attention kernels are CUDA libraries. They are not part of this macOS setup. On MPS, Transformers uses its reference implementation. A real question is therefore slower than the fixed greeting. This release does not add a second Qwen runtime.

## Prerequisites

- Python 3.12. The package metadata allows 3.10 and newer, and the local model stack was checked with 3.12. Do not assume a newer system Python can load the pinned PyTorch wheel.
- `curl`, used only by the model installer.
- `llama-server` on `PATH`. On Apple Silicon the tested install is Homebrew `llama.cpp`, which is a Metal build:

```bash
brew install llama.cpp
```

A CPU-only `llama-server` cannot accelerate Mica. The launcher still starts it, with GPU layers set to `0` outside Apple Silicon.

## Installation

Clone the repository and create the virtual environment in the repository root. These commands use that directory, not a home-directory path.

macOS and Linux:

```bash
git clone https://github.com/bekirs01/yandex-llm-connector.git
cd yandex-llm-connector
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r local_models/requirements.txt
```

Windows PowerShell:

```powershell
git clone https://github.com/bekirs01/yandex-llm-connector.git
cd yandex-llm-connector
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r local_models/requirements.txt
```

The optional Yandex client and its tests are separate:

```bash
python -m pip install -e ".[dev]"
```

That extra is not required to start the local chat.

## Model download and configuration

The trained adapters are in the repository:

- `local_models/mica_baseline_lora.gguf`
- `local_models/qwen_project/trained_model/qwen3.5-0.8b-lora/`

The base weights are not redistributed here. `local_models/setup_models.py` downloads them from the public Hugging Face revisions pinned in that file, and only when the local file is missing or does not match the pinned size or SHA-256.

- Mica Q4: `https://huggingface.co/sky7350/Mica-v0.1-4B` at revision `ca36594cc2067c7252704f9f304cc10ef11c7c5c`, file `mica-v0.1-4b-Q4_K_M.gguf` (3,066,384,768 bytes).
- Qwen3.5 0.8B: `https://huggingface.co/Qwen/Qwen3.5-0.8B` at revision `2fc06364715b967f1860aea9cf38778875588b17`, file `model.safetensors-00001-of-00001.safetensors`.

Run this once. It is a multi-gigabyte download. Starting the application does not download these files.

```bash
python local_models/setup_models.py
```

The files are written under `local_models/models/mica/` and `local_models/qwen_project/models/qwen3.5-0.8b/`. Those directories are gitignored.

## Environment setup

Copy the example only if you use the optional Yandex client:

```bash
cp .env.example .env
```

Do not commit `.env`. The local launcher does not read Yandex credentials.

The launcher and the extractor understand these variables. Defaults are shown.

| Variable | Default | Role |
| --- | --- | --- |
| `AUTOSERVICE_UI_PORT` | `8766` | Web UI port |
| `AUTOSERVICE_EXTRACT_PORT` | `8767` | Mica + Qwen extract service |
| `AUTOSERVICE_MICA_PORT` | `8768` | llama.cpp server |
| `AUTOSERVICE_MICA_URL` | `http://127.0.0.1:8768/completion` | Extractor's Mica endpoint |
| `AUTOSERVICE_MICA_NGL` | `all` on macOS arm64, otherwise `0` | llama.cpp GPU layers |
| `AUTOSERVICE_MODEL_URL` | set by the launcher to the local extract URL | Makes the web UI use local inference |

All services bind to `127.0.0.1`.

## How to start the application

From the repository root, with the virtual environment active:

```bash
python local_models/start_preview.py
```

The command checks that the base weights and `llama-server` exist. It does not download models. It starts only the services that are not already healthy:

- Mica on port 8768, with Metal offload on Apple Silicon.
- The Qwen extractor on port 8767. On Apple Silicon the device is MPS and the weights stay in bfloat16. `PYTORCH_ENABLE_MPS_FALLBACK=1` is set for operations MPS does not implement.
- The web UI on port 8766.

If a port is already serving this application's health URL, that service is reused. If a port is occupied by something that does not answer the health URL, the launcher stops and tells you the port. It does not kill that process.

Ctrl+C stops only the processes started by that launcher.

To use another UI port:

```bash
AUTOSERVICE_UI_PORT=8769 python local_models/start_preview.py
```

## How to access the local web interface

Open the URL printed by the launcher. The default is:

http://127.0.0.1:8766

The page is the service chat. Health for the UI is `GET /api/health`. Health for the extractor is `GET http://127.0.0.1:8767/health`.

## Troubleshooting

- `Missing model files` — run `python local_models/setup_models.py`. A failed download is not retried by the launcher.
- `Qwen base weight SHA-256 mismatch` or an incomplete Mica file — delete that file and run the installer again. The installer checks the pinned Qwen SHA-256 and the pinned Mica size.
- `llama-server was not found on PATH` — install it and open a new shell. On Apple Silicon, `brew install llama.cpp`.
- `port ... is in use` — another process owns that port. Choose another `AUTOSERVICE_*_PORT` or stop that process yourself. The launcher will not stop it.
- The UI returns `Not found` after the project directory was moved — stop that UI process and start it again from the repository root. The server reads files from the checkout.
- Qwen reports that MPS is unavailable — the process is not on Apple Silicon, or PyTorch was installed without MPS. The CPU path still runs.
- Mica logs CPU fallback for every tensor — `llama-server` was started with GPU layers disabled, or the binary has no Metal backend. On Apple Silicon, leave `AUTOSERVICE_MICA_NGL` unset so the launcher passes `-ngl all`.
- A real question stays pending for a long time — the extractor is still running. The greeting does not measure model speed. On CPU this can take several minutes. On Apple Silicon, Mica is offloaded, and Qwen still uses the reference linear-attention scan.

## Known limitations

- Reply quality is the current development baseline. The dialogue policy and the Russian wording are not being retuned in this release.
- The policy does not invent prices, opening hours, or bookings.
- Qwen on MPS is not a fused Metal kernel. Expect a real answer to take noticeably longer than the greeting.
- Linux, Windows, and Intel Macs do not get Metal or MPS from this setup.
- A dropped browser connection is noticed between Mica calls and between Qwen tokens. The model lock is not held for a finished client. Prefill that is already inside one model call is not cancelled mid-kernel.
- Services listen only on localhost.

## Privacy and local inference

With the launcher, chat requests go to `http://127.0.0.1`. The extractor loads the local files and sets Hugging Face offline mode. It does not call Yandex Cloud.

The model installer is the step that uses the network, and only to download the two public base files.

Yandex credentials in `.env` or in the browser credential fields are used only when the UI is started without `AUTOSERVICE_MODEL_URL`. The browser does not write those credentials to disk. Do not commit `.env`, API keys, or the downloaded base weights.
