"""Local web app: grid, semantic map, search and the Update button. Serves media straight from the data folder."""
import json
import os
import subprocess
import sys
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, ValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, update
from .cluster import LAYOUT_PATH

STATIC = Path(__file__).parent / "static"
UPDATE_LOG = db.DATA_DIR / "update.log"
app = FastAPI(title="SavedMap")
app.add_middleware(GZipMiddleware, minimum_size=1000)
job: dict = {"proc": None}  # the one running `savedmap update`, if any
# A copy that another machine keeps up to date (e.g. a server): browse and search only, no updates or settings
READ_ONLY = os.environ.get("SAVEDMAP_READ_ONLY") == "1"


def writable():
    if READ_ONLY:
        raise HTTPException(403, "This copy is read-only: updates and settings live on the machine that syncs it")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


LIST_DETAILS = ("likes", "rating", "year", "pages", "duration", "unavailable", "domain")  # the rest comes with /api/item


@app.get("/api/data")
def data():
    """Everything the grid, map and filters need, kept small (gzip on top): long texts such as
    transcripts and on-screen text are fetched per item when it is opened."""
    con = db.connect()
    members: dict[str, list[str]] = {}
    for r in con.execute("SELECT collection_id, item_id FROM memberships"):
        members.setdefault(r["item_id"], []).append(r["collection_id"])
    media: dict[str, int] = {}
    video: set[str] = set()
    for r in con.execute("SELECT item_id, kind FROM media WHERE path IS NOT NULL AND kind != 'cover'"):
        media[r["item_id"]] = media.get(r["item_id"], 0) + 1
        if r["kind"] == "video":
            video.add(r["item_id"])
    items = []
    for r in con.execute("""SELECT i.id, i.source, i.kind, i.url, i.author, i.title AS item_title, substr(i.text, 1, 200) AS text,
                                   i.created_at, i.details, i.status, a.title AS llm_title, a.summary, a.tags, a.topics
                            FROM items i LEFT JOIN analysis a ON a.item_id = i.id
                            WHERE i.download_done=1 ORDER BY i.saved_pos"""):
        details = json.loads(r["details"] or "{}")
        items.append({
            "id": r["id"], "source": r["source"], "kind": r["kind"], "url": r["url"], "author": r["author"],
            "name": r["item_title"], "created_at": r["created_at"], "removed": r["status"] == "removed",
            "details": {k: details[k] for k in LIST_DETAILS if details.get(k) is not None},
            "collections": members.get(r["id"], []), "n_media": media.get(r["id"], 0), "video": r["id"] in video,
            "title": r["llm_title"], "summary": ((r["summary"] or r["text"] or "")[:110]) or None,  # full one with the item
            "topics": json.loads(r["topics"]) if r["topics"] else [],
            "thumb": db.thumb_path(r["id"]).exists(),  # the browser builds /thumbs/<source>/<id>.webp
        })
    cols = [dict(r) for r in con.execute("""SELECT c.id, c.source, c.name, COUNT(m.item_id) n FROM collections c
                                            LEFT JOIN memberships m ON m.collection_id=c.id GROUP BY c.id HAVING n > 0 ORDER BY c.name""")]
    return {"items": items, "collections": cols}


@app.get("/api/layout")
def layout():
    """The map: loaded after the first paint, so the grid shows without waiting for it."""
    return json.loads(LAYOUT_PATH.read_text()) if LAYOUT_PATH.exists() else {}


@app.get("/api/item/{item_id}")
def item(item_id: str):
    """The long parts of one item, for the viewer: full text, transcript, on-screen text, media files."""
    con = db.connect()
    r = con.execute("""SELECT i.text, i.details, a.transcript, a.ocr, a.summary, a.tags FROM items i
                       LEFT JOIN analysis a ON a.item_id = i.id WHERE i.id = ?""", (item_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "No such item")
    media, cover = [], None
    for m in con.execute("SELECT kind, path FROM media WHERE item_id=? AND path IS NOT NULL ORDER BY idx", (item_id,)):
        if m["kind"] == "cover":
            cover = f"/media/{m['path']}"
        else:
            media.append({"kind": m["kind"], "url": f"/media/{m['path']}"})
    return {"text": r["text"], "transcript": r["transcript"], "ocr": r["ocr"], "details": json.loads(r["details"] or "{}"),
            "media": media, "cover": cover, "summary": r["summary"] or None,
            "tags": json.loads(r["tags"]) if r["tags"] else []}


@lru_cache(maxsize=1)
def encoders():
    from .process import Siglip, load_e5
    return Siglip("cpu"), load_e5("cpu")  # one query at a time: CPU is fast enough and leaves the GPU free


_emb: dict = {"key": None}


def embeddings() -> tuple[list[str], np.ndarray, np.ndarray]:
    """(ids, visual, text) for every embedded item, cached until items are added or re-embedded."""
    con = db.connect()
    key = con.execute("SELECT COUNT(*), SUM(length(text_emb)) FROM analysis WHERE visual_emb IS NOT NULL AND text_emb IS NOT NULL").fetchone()
    if _emb["key"] != tuple(key):
        rows = con.execute("SELECT item_id, visual_emb, text_emb FROM analysis WHERE visual_emb IS NOT NULL AND text_emb IS NOT NULL").fetchall()
        _emb.update(key=tuple(key), ids=[r["item_id"] for r in rows],
                    vis=np.stack([db.from_blob(r["visual_emb"]) for r in rows]) if rows else np.zeros((0, 1)),
                    txt=np.stack([db.from_blob(r["text_emb"]) for r in rows]) if rows else np.zeros((0, 1)))
        _emb["index"] = {i: n for n, i in enumerate(_emb["ids"])}
    return _emb["ids"], _emb["vis"], _emb["txt"]


def zscore(s: np.ndarray) -> np.ndarray:
    return (s - s.mean()) / (s.std() + 1e-9)


@app.get("/api/search")
def search(q: str, k: int = 60):
    """Rank items by text→image (SigLIP2) plus text→text (e5) similarity, each z-scored."""
    ids, vis, txt = embeddings()
    if not ids or not q.strip():
        return {"results": []}
    sig, e5 = encoders()
    score = zscore(vis @ sig.text(q)) + zscore(txt @ e5.encode("query: " + q, normalize_embeddings=True))
    top = score.argsort()[::-1][:k]
    return {"results": [{"id": ids[i], "score": round(float(score[i]), 3)} for i in top]}


@app.get("/api/related/{item_id}")
def related(item_id: str, k: int = 8):
    """The items most like this one, by look and by topic together, from any platform."""
    ids, vis, txt = embeddings()
    n = _emb["index"].get(item_id)
    if n is None:
        return {"results": []}
    score = zscore(vis @ vis[n]) + zscore(txt @ txt[n])
    top = [i for i in score.argsort()[::-1][:61] if i != n][:60]
    source = item_id.split(":", 1)[0]
    # the library is mostly one platform: keep two slots for the best matches from the others
    others = [i for i in top if not ids[i].startswith(source + ":")][:2]
    picked = set(others) | set([i for i in top if i not in others][:k - len(others)])
    return {"results": [ids[i] for i in top if i in picked]}


@app.get("/api/settings")
def get_settings():
    writable()
    from .process import USER_TOPICS, topic_list
    return {"config": config.load().model_dump(), "schema": config.Config.model_json_schema(),
            "topics": topic_list(), "custom_topics": USER_TOPICS.exists(), "path": str(config.PATH)}


class SettingsIn(BaseModel):
    config: dict
    topics: list[str]


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    """Validate everything first, then write config.toml (comments kept) and the topic list."""
    writable()
    from .process import USER_TOPICS, topic_list
    try:
        cfg = config.Config.model_validate(body.config)
    except ValidationError as e:
        raise HTTPException(422, [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()])
    topics = list(dict.fromkeys(t.strip() for t in body.topics if t.strip()))
    if len(topics) < 2:
        raise HTTPException(422, ["topics: keep at least two"])
    config.save(cfg)
    changed = topics != topic_list()
    if changed:
        USER_TOPICS.write_text("# Your topics (Settings). Items are re-tagged on the next update.\n" + "\n".join(topics) + "\n")
    return {"saved": True, "topics_changed": changed}


def running() -> bool:
    return job["proc"] is not None and job["proc"].poll() is None


@app.get("/api/update")
def update_status():
    lines = UPDATE_LOG.read_text(errors="replace").replace("\r", "\n").splitlines() if UPDATE_LOG.exists() else []
    return {"read_only": READ_ONLY, "running": running(), "exit": None if running() or job["proc"] is None else job["proc"].returncode,
            "log": [l for l in lines if l.strip()][-12:], "sources": update.status(db.connect(), config.load())}


@app.post("/api/update")
def start_update():
    writable()
    if running():
        raise HTTPException(409, "An update is already running")
    log = UPDATE_LOG.open("w")
    job["proc"] = subprocess.Popen([sys.executable, "-u", "-m", "savedmap.cli", "update"], stdout=log, stderr=subprocess.STDOUT,
                                   cwd=db.ROOT, start_new_session=True)
    return {"running": True}


class CachedStatic(StaticFiles):
    """Static files with an explicit cache policy: app code revalidates on every load (ETag, so an edited
    app.js is never stale); media and thumbnails don't change, so the browser keeps them for a month."""

    def __init__(self, *args, policy: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy = policy

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = self.policy
        return resp


def serve(host: str, port: int):
    import uvicorn
    db.connect()  # fails early with a clear message if the data folder needs `savedmap migrate`
    db.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    db.THUMB_DIR.mkdir(parents=True, exist_ok=True)
    month = "public, max-age=2592000"
    app.mount("/media", CachedStatic(directory=db.MEDIA_DIR, policy=month), name="media")
    app.mount("/thumbs", CachedStatic(directory=db.THUMB_DIR, policy=month), name="thumbs")
    app.mount("/static", CachedStatic(directory=STATIC, policy="no-cache"), name="static")
    threading.Thread(target=lambda: (embeddings(), encoders()), daemon=True).start()  # warm search and related now
    print(f"SavedMap on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
