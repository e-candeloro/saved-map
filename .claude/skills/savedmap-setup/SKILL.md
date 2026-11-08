---
name: savedmap-setup
description: Install and configure SavedMap on this machine. Checks the GPU, ffmpeg, uv and Chrome, installs Python deps and Ollama with the small model, creates the data folder and config.toml. Use when someone clones SavedMap, asks to set it up, or a SavedMap command fails because something is missing.
---

# SavedMap setup

Goal: `uv run savedmap serve` works and `data/config.toml` exists. Platforms are connected afterwards with the `connect-*` skills. Run each step, check its result, and only fix what is missing.

## 1. Check the machine

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv   # optional: NVIDIA GPU (4 GB is enough)
ffmpeg -version | head -1                               # required: video frames and audio
uv --version                                            # required: Python env manager
google-chrome --version                                 # required for Instagram/Pinterest login
```

- No GPU: everything still works on the CPU, just slower. Transcribing ~30 h of audio takes about a day. Offer a cloud transcription key instead (step 5).
- Missing ffmpeg, uv or Chrome: tell the user the one install command for their OS, for example `sudo apt install ffmpeg` or `curl -LsSf https://astral.sh/uv/install.sh | sh`. Never run sudo yourself.

## 2. Python dependencies

```bash
uv sync
```

The torch wheels in `pyproject.toml` use CUDA 12.8. On a CPU-only machine this still works, but the download is big.

## 3. Data folder and config

```bash
uv run savedmap init
```

This creates `data/` (gitignored) and `data/config.toml`. To keep media on a bigger disk, make `data` a symlink before running `init`, e.g. `ln -s /mnt/disk/SavedMap data`. Ask the user where they want it, because media can take tens of GB (about 18 GB for ~2800 Instagram saves).

## 4. Local LLM (Ollama)

Skip this if the user wants a cloud LLM (step 5).

Install without sudo:

```bash
mkdir -p ~/.local/ollama
curl -fL https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst | tar --zstd -x -C ~/.local/ollama
~/.local/ollama/bin/ollama --version
```

SavedMap finds Ollama on PATH or in `~/.local/ollama`. It starts the server and pulls `qwen3:1.7b` (~1.4 GB) the first time `refine` runs. On macOS, use the Ollama app.

## 5. Optional: cloud models

Ask the user before setting this up: the cloud options send audio and text to the provider. Settings go in `data/config.toml`, and keys only ever go in environment variables.

- **Transcription:** in `[models.transcribe]`, set `backend = "api"`; the defaults point to Groq `whisper-large-v3-turbo` (≈ $0.04 per audio hour). The user exports `GROQ_API_KEY`.
- **LLM:** in `[models.llm]`, set `base_url`, `model`, `api_key_env` and `reasoning_effort = ""`. Any OpenAI-compatible endpoint works: OpenAI, OpenRouter, Groq, or Gemini's OpenAI endpoint.

## 6. Verify

```bash
uv run pytest -q
uv run savedmap status
```

Then continue with `/connect-instagram`, `/connect-pinterest` or `/connect-goodreads`.
