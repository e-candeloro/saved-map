"""SQLite storage. One file next to the media, so the data folder is self-contained.

Items from every platform share one table; `id` is "<source>:<native id>".
"""
import os
import sqlite3
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SAVEDMAP_DATA", ROOT / "data")).expanduser()  # ./data may be a symlink to a bigger disk
MEDIA_DIR = DATA_DIR / "media"
THUMB_DIR = DATA_DIR / "thumbs"
FRAMES_DIR = DATA_DIR / "frames"
DB_PATH = DATA_DIR / "savedmap.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,            -- <source>:<native id>
    source TEXT NOT NULL,           -- instagram | pinterest | goodreads
    native_id TEXT NOT NULL,
    kind TEXT NOT NULL,             -- post | pin | book
    url TEXT,                       -- the item on its platform
    author TEXT,
    title TEXT,                     -- platform title (books, pins); the LLM title lives in analysis
    text TEXT,                      -- caption / description / review
    created_at INTEGER,
    details TEXT,                   -- JSON: platform extras shown in the viewer (likes, rating, ...)
    raw TEXT,                       -- full platform record, refreshed on every sync
    saved_pos INTEGER,              -- order within its source, lower = saved more recently
    status TEXT DEFAULT 'active',   -- active | removed (no longer saved on the platform)
    removed_at INTEGER,
    download_done INTEGER DEFAULT 0,
    first_seen INTEGER DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS items_source ON items(source, saved_pos);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,            -- <source>:<native id>
    source TEXT NOT NULL,
    name TEXT,
    url TEXT
);
CREATE TABLE IF NOT EXISTS memberships (
    collection_id TEXT, item_id TEXT,
    PRIMARY KEY (collection_id, item_id)
);
CREATE TABLE IF NOT EXISTS media (
    item_id TEXT, idx INTEGER,
    kind TEXT,                      -- image | video | cover
    path TEXT,                      -- relative to MEDIA_DIR; NULL until downloaded
    url TEXT,                       -- where to download it from
    PRIMARY KEY (item_id, idx)
);
CREATE TABLE IF NOT EXISTS analysis (
    item_id TEXT PRIMARY KEY,
    transcript TEXT, language TEXT,
    ocr TEXT,
    visual_emb BLOB,                -- float32, L2-normalised SigLIP mean of images/frames
    text_emb BLOB,                  -- float32, L2-normalised sentence embedding
    title TEXT, summary TEXT,
    tags TEXT,                      -- JSON list, free-form (cluster labels)
    topics TEXT                     -- JSON list from topics.txt (topic filter)
);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=60)  # update and process may write at the same time
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='posts'").fetchone():
        raise SystemExit("This data folder still has the Instagram-only layout: run `savedmap migrate` once.")
    con.executescript(SCHEMA)
    return con


def item_dir(item_id: str) -> str:
    """'instagram:ABC' -> 'instagram/ABC': the item's folder under media/ and frames/."""
    source, native = item_id.split(":", 1)
    return f"{source}/{native}"


def thumb_path(item_id: str) -> Path:
    return THUMB_DIR / f"{item_dir(item_id)}.webp"  # 256 px WebP: grid tiles and map sprites


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes | None) -> np.ndarray | None:
    return None if b is None else np.frombuffer(b, dtype=np.float32)


def get_meta(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(con, key, value):
    con.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
