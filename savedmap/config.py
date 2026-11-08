"""Settings in <data folder>/config.toml, validated with pydantic. API keys are never stored here:
`api_key_env` names the environment variable that holds the key."""
import os
import tomllib
from typing import Literal

import tomlkit
from pydantic import BaseModel, ConfigDict, Field

from . import db

PATH = db.DATA_DIR / "config.toml"

TEMPLATE = """\
# SavedMap settings. API keys never go in this file: set them as environment variables
# and put the variable's name in api_key_env.

[sources.instagram]
enabled = false
user = ""                 # your username, as in instagram.com/<user>/

[sources.pinterest]
enabled = false
user = ""                 # profile name, as in pinterest.com/<user>/
login = false             # true: use your login (savedmap connect pinterest) to include secret boards

[sources.goodreads]
enabled = false
# your library export (goodreads.com → My Books → Tools → Import and export); the newest match is used
export_csv = "~/Downloads/goodreads_library_export*.csv"

[sources.youtube]
enabled = false
# Google Takeout (YouTube and YouTube Music → playlists, music library), unpacked; liked videos are not in it
takeout = "~/Downloads/Takeout"
skip_playlists = ["Watch later"]
music_library = true

[models]
device = "auto"           # auto | cuda | cpu (Whisper, OCR, embeddings)

[models.llm]              # any OpenAI-compatible chat endpoint; default: local Ollama
base_url = "http://localhost:11434/v1"
model = "qwen3:1.7b"
api_key_env = ""          # e.g. "OPENAI_API_KEY" for a cloud endpoint
reasoning_effort = "none" # "none" turns off thinking on Ollama; cloud models may want "minimal" or ""

[models.transcribe]
backend = "local"         # local (faster-whisper) | api (OpenAI-compatible /audio/transcriptions)
base_url = "https://api.groq.com/openai/v1"
model = "whisper-large-v3-turbo"
api_key_env = "GROQ_API_KEY"

[guard]                   # limits for platforms that need your login
min_hours_between_syncs = 12
max_pages = 40            # per incremental sync
max_pages_full = 200      # first sync or --full
full_sync_min_days = 30
cooldown_hours = 72       # pause after the platform pushes back
"""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in config.toml is an error, not a silent default


class Instagram(Strict):
    enabled: bool = False
    user: str = Field("", description="Your username, as in instagram.com/<user>/")


class Pinterest(Strict):
    enabled: bool = False
    user: str = Field("", description="Profile name, as in pinterest.com/<user>/")
    login: bool = Field(False, description="Include secret boards (log in once with `savedmap connect pinterest`)")


class Goodreads(Strict):
    enabled: bool = False
    export_csv: str = Field("~/Downloads/goodreads_library_export*.csv",
                            description="Library export from Goodreads (My Books → Tools → Import and export); the newest match is used")


class YouTube(Strict):
    enabled: bool = False
    takeout: str = Field("~/Downloads/Takeout", description="Unpacked Google Takeout folder (YouTube and YouTube Music → playlists, music library)")
    skip_playlists: list[str] = Field(["Watch later"], description="Playlists to leave out, comma separated")
    music_library: bool = Field(True, description="Also import your YouTube Music library songs")


class Sources(Strict):
    instagram: Instagram = Instagram()
    pinterest: Pinterest = Pinterest()
    goodreads: Goodreads = Goodreads()
    youtube: YouTube = YouTube()


class Endpoint(Strict):
    base_url: str
    model: str
    api_key_env: str = Field("", description="Name of the environment variable holding the API key (never the key itself); empty for local servers")

    def api_key(self) -> str:
        if not self.api_key_env:
            return "none"  # local servers ignore it, but the client needs a value
        key = os.environ.get(self.api_key_env)
        if not key:
            raise SystemExit(f"Set the environment variable {self.api_key_env} (see config.toml)")
        return key


class LLM(Endpoint):
    base_url: str = Field("http://localhost:11434/v1", description="Any OpenAI-compatible chat endpoint; default is local Ollama")
    model: str = Field("qwen3:1.7b", description="Model name at that endpoint")
    reasoning_effort: str = Field("none", description='"none" turns thinking off on Ollama; cloud models may want "minimal" or empty')


class Transcribe(Endpoint):
    backend: Literal["local", "api"] = Field("local", description="local = faster-whisper on this machine; api = OpenAI-compatible /audio/transcriptions")
    base_url: str = Field("https://api.groq.com/openai/v1", description="Used when backend is api")
    model: str = Field("whisper-large-v3-turbo", description="Used when backend is api")
    api_key_env: str = Field("GROQ_API_KEY", description="Environment variable holding the API key (backend api)")


class Models(Strict):
    device: Literal["auto", "cuda", "cpu"] = Field("auto", description="Where Whisper, OCR and embeddings run")
    llm: LLM = LLM()
    transcribe: Transcribe = Transcribe()


class Guard(Strict):
    min_hours_between_syncs: float = Field(12, ge=1, description="Per platform with a login")
    max_pages: int = Field(40, ge=1, le=500, description="Requests per normal update")
    max_pages_full: int = Field(200, ge=1, le=1000, description="Requests for the first sync or a full re-read")
    full_sync_min_days: float = Field(30, ge=1, description="Days between full re-reads")
    cooldown_hours: float = Field(72, ge=1, description="Pause after a platform pushes back")


class Config(Strict):
    sources: Sources = Sources()
    models: Models = Models()
    guard: Guard = Guard()


def load() -> Config:
    if not PATH.exists():
        return Config()
    with PATH.open("rb") as f:
        return Config.model_validate(tomllib.load(f))


def save(cfg: Config) -> None:
    """Write validated settings back into config.toml, keeping its comments and layout (tomlkit)."""
    doc = tomlkit.parse(PATH.read_text() if PATH.exists() else TEMPLATE)

    def merge(table, values: dict):
        for k, v in values.items():
            if isinstance(v, dict):
                if k not in table:
                    table[k] = tomlkit.table()
                merge(table[k], v)
            else:
                table[k] = v
    merge(doc, cfg.model_dump())
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(tomlkit.dumps(doc))


def init() -> None:
    if PATH.exists():
        print(f"{PATH} already exists")
        return
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(TEMPLATE)
    print(f"Wrote {PATH}: enable your platforms there")
