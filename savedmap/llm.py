"""One client for every model endpoint: local Ollama by default, any OpenAI-compatible API by config.
Structured output: a pydantic model becomes the JSON schema and validates the answer."""
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from openai import OpenAI
from pydantic import BaseModel

from . import db
from .config import Endpoint, LLM

LOCAL_OLLAMA = Path.home() / ".local/ollama/bin/ollama"  # where /savedmap-setup unpacks it without sudo


def client(ep: Endpoint) -> OpenAI:
    return OpenAI(base_url=ep.base_url, api_key=ep.api_key(), timeout=180, max_retries=2)


def is_local_ollama(ep: LLM) -> bool:
    u = urlparse(ep.base_url)
    return u.hostname in ("localhost", "127.0.0.1") and u.port == 11434


def ensure_ollama(ep: LLM) -> None:
    """Start the local Ollama server if it isn't running, and pull the model if missing."""
    if not is_local_ollama(ep):
        return
    root = ep.base_url.rsplit("/v1", 1)[0]
    exe = shutil.which("ollama") or (str(LOCAL_OLLAMA) if LOCAL_OLLAMA.exists() else None)

    def up() -> bool:
        try:
            return httpx.get(f"{root}/api/version", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    if not up():
        if not exe:
            raise SystemExit("Ollama is not installed or running: see the savedmap-setup skill, or set [models.llm] to a cloud endpoint")
        log = (db.DATA_DIR / "ollama.log").open("a")
        subprocess.Popen([exe, "serve"], stdout=log, stderr=log, start_new_session=True)
        for _ in range(60):
            if up():
                break
            time.sleep(1)
        else:
            raise SystemExit(f"Ollama did not start; see {db.DATA_DIR / 'ollama.log'}")
    if httpx.post(f"{root}/api/show", json={"model": ep.model}, timeout=10).status_code != 200:
        if not exe:
            raise SystemExit(f"Model {ep.model} missing: run `ollama pull {ep.model}`")
        print(f"Pulling {ep.model} (one time)…")
        subprocess.run([exe, "pull", ep.model], check=True)


def structured[T: BaseModel](cl: OpenAI, ep: LLM, messages: list[dict], schema: type[T], max_tokens: int = 400) -> T | None:
    """Chat completion constrained to `schema`; None when the model fails twice."""
    extra = {"reasoning_effort": ep.reasoning_effort} if ep.reasoning_effort else {}
    err: Exception | str = "empty answer"
    for _ in range(2):
        try:
            r = cl.chat.completions.parse(model=ep.model, messages=messages, response_format=schema,
                                          temperature=0.2, max_tokens=max_tokens, **extra)
            if r.choices[0].message.parsed is not None:
                return r.choices[0].message.parsed
        except Exception as e:  # invalid JSON, schema mismatch, timeout: retry once
            err = e
    print(f"\n  ! LLM: {str(err)[:200]}")
    return None


def transcribe(cl: OpenAI, model: str, audio_mp3: bytes) -> tuple[str, str | None]:
    """Cloud speech-to-text (OpenAI-compatible /audio/transcriptions). Returns (text, language)."""
    r = cl.audio.transcriptions.create(model=model, file=("audio.mp3", audio_mp3), response_format="verbose_json")
    return r.text.strip(), getattr(r, "language", None)
