"""Storage, ban guard and migration, without network."""
import json
import sqlite3
import time

from savedmap import db, migrate, update
from savedmap.config import Config
from savedmap.sources import SOURCES
from savedmap.sources.base import Batch, Item, Media


def item(n, cols=(), media=1):
    return Item(native_id=f"p{n}", kind="post", url=f"https://x/{n}", text=f"post {n}",
                collections=list(cols), media=[Media(kind="image", url=f"https://cdn/{n}.jpg")] * media)


def ids(con):
    return [r[0] for r in con.execute("SELECT native_id FROM items WHERE status='active' ORDER BY saved_pos")]


def test_incremental_puts_new_saves_first(con):
    update.store(con, "instagram", Batch(items=[item(2), item(1)], complete=True), resumed=False)
    assert update.store(con, "instagram", Batch(items=[item(4), item(3), item(2)]), resumed=False) == 2
    assert ids(con) == ["p4", "p3", "p2", "p1"]


def test_duplicate_from_another_platform_is_merged(con):
    update.store(con, "instagram", Batch(items=[item(1, [("c1", "Food")])], complete=True), resumed=False)
    dup = Item(native_id="k1", kind="bookmark", url="https://kk/k1", collections=[("l1", "Recipes")], same_as="instagram:p1")
    alone = Item(native_id="k2", kind="bookmark", url="https://kk/k2", same_as="instagram:missing")
    update.store(con, "karakeep", Batch(items=[dup, alone], complete=True), resumed=False)
    members = lambda: sorted(r[0] for r in con.execute("SELECT collection_id FROM memberships WHERE item_id='instagram:p1'"))
    assert members() == ["instagram:c1", "karakeep:l1"]
    assert [r[0] for r in con.execute("SELECT id FROM items WHERE source='karakeep'")] == ["karakeep:k2"]
    update.store(con, "instagram", Batch(items=[item(1, [("c1", "Food")])]), resumed=False)  # its own sync keeps the list
    assert members() == ["instagram:c1", "karakeep:l1"]
    update.store(con, "karakeep", Batch(items=[alone], complete=True), resumed=False)  # bookmark deleted in Karakeep
    assert members() == ["instagram:c1"]


def test_resumed_run_appends_older_items(con):
    update.store(con, "instagram", Batch(items=[item(2), item(1)], cursor="c"), resumed=False)
    update.store(con, "instagram", Batch(items=[item(0)]), resumed=True)
    assert ids(con) == ["p2", "p1", "p0"]


def test_complete_batch_marks_unsaved_as_removed_and_restores(con):
    update.store(con, "instagram", Batch(items=[item(3), item(2), item(1)], complete=True), resumed=False)
    update.store(con, "instagram", Batch(items=[item(3), item(1)], complete=True), resumed=False)
    assert ids(con) == ["p3", "p1"]
    assert con.execute("SELECT status FROM items WHERE native_id='p2'").fetchone()[0] == "removed"
    update.store(con, "instagram", Batch(items=[item(2)]), resumed=False)  # saved again
    assert con.execute("SELECT status FROM items WHERE native_id='p2'").fetchone()[0] == "active"


def test_collections_and_media(con):
    update.store(con, "instagram", Batch(items=[item(1, [("c1", "Books")], media=2)], complete=True), resumed=False)
    assert con.execute("SELECT name FROM collections WHERE id='instagram:c1'").fetchone()[0] == "Books"
    assert con.execute("SELECT COUNT(*) FROM media WHERE item_id='instagram:p1' AND path IS NULL").fetchone()[0] == 2
    # a later sync without the name (Instagram only names collections it saw on the page) keeps it
    update.store(con, "instagram", Batch(items=[item(1, [("c1", "")])]), resumed=False)
    assert con.execute("SELECT name FROM collections WHERE id='instagram:c1'").fetchone()[0] == "Books"


def test_guard(con):
    cfg, ig = Config(), SOURCES["instagram"]
    now = time.time()
    assert update.blocked_reason(con, cfg, ig, full=False, now=now) == (None, None)
    db.set_meta(con, "sync:instagram:last", now - 3600)
    assert "Synced recently" in update.blocked_reason(con, cfg, ig, full=False, now=now)[0]
    assert update.blocked_reason(con, cfg, ig, full=False, now=now + 12 * 3600)[0] is None
    db.set_meta(con, "sync:instagram:last_full", now)
    assert "Full instagram sync" in update.blocked_reason(con, cfg, ig, full=True, now=now + 13 * 3600)[0]
    db.set_meta(con, "sync:instagram:cooldown_until", now + 72 * 3600)
    db.set_meta(con, "sync:instagram:cooldown_reason", "HTTP 429")
    assert "HTTP 429" in update.blocked_reason(con, cfg, ig, full=False, now=now + 13 * 3600)[0]
    assert "HTTP 429" in update.blocked_reason(con, cfg, ig, full=False, now=now + 13 * 3600, force=True)[0]  # force never skips a pause
    db.set_meta(con, "sync:instagram:cooldown_until", 0)
    assert update.blocked_reason(con, cfg, ig, full=False, now=now + 60, force=True) == (None, None)


def test_migration_from_v01(con):
    con.close()
    db.DB_PATH.unlink()
    for f in db.DATA_DIR.glob("savedmap.db*"):
        f.unlink()
    old = sqlite3.connect(db.DB_PATH)
    old.executescript("""
        CREATE TABLE posts (code TEXT PRIMARY KEY, pk TEXT, media_type INTEGER, product_type TEXT, username TEXT, caption TEXT,
            taken_at INTEGER, like_count INTEGER, raw TEXT, saved_pos INTEGER, download_done INTEGER DEFAULT 0, first_seen INTEGER);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT, url TEXT);
        CREATE TABLE memberships (collection_id TEXT, code TEXT, PRIMARY KEY (collection_id, code));
        CREATE TABLE media (code TEXT, idx INTEGER, kind TEXT, path TEXT, PRIMARY KEY (code, idx));
        CREATE TABLE analysis (code TEXT PRIMARY KEY, transcript TEXT, language TEXT, ocr TEXT, visual_emb BLOB, text_emb BLOB,
            title TEXT, summary TEXT, tags TEXT);
        INSERT INTO posts VALUES ('ABC', '1', 2, 'clips', 'someone', 'hello', 100, 5, '{}', 0, 1, 1000);
        INSERT INTO meta VALUES ('user', 'me');
        INSERT INTO collections VALUES ('9', 'Books', 'u');
        INSERT INTO memberships VALUES ('9', 'ABC');
        INSERT INTO media VALUES ('ABC', 0, 'video', 'ABC/0.mp4');
        INSERT INTO analysis (code, transcript, title, tags) VALUES ('ABC', 'hi', 'T', '["a"]');""")
    old.commit()
    old.close()
    (db.MEDIA_DIR / "ABC").mkdir(parents=True)
    (db.MEDIA_DIR / "ABC" / "0.mp4").write_bytes(b"x")

    migrate.run()
    c = db.connect()
    row = c.execute("SELECT * FROM items").fetchone()
    assert (row["id"], row["author"], row["text"], json.loads(row["details"])["likes"]) == ("instagram:ABC", "someone", "hello", 5)
    assert c.execute("SELECT path FROM media").fetchone()[0] == "instagram/ABC/0.mp4"
    assert (db.MEDIA_DIR / "instagram/ABC/0.mp4").exists()
    assert c.execute("SELECT item_id FROM memberships").fetchone()[0] == "instagram:ABC"
    assert c.execute("SELECT title FROM analysis").fetchone()[0] == "T"
    assert db.get_meta(c, "sync:instagram:last") == "1000"
    migrate.run()  # safe to re-run


def test_settings_api(con):
    from fastapi.testclient import TestClient
    from savedmap import config, web
    config.init()
    client = TestClient(web.app)
    s = client.get("/api/settings").json()
    assert s["config"]["guard"]["max_pages"] == 40 and "books & reading" in s["topics"]
    bad = s["config"] | {"guard": s["config"]["guard"] | {"max_pages": 0}}
    r = client.put("/api/settings", json={"config": bad, "topics": s["topics"]})
    assert r.status_code == 422 and "guard.max_pages" in r.json()["detail"][0]
    good = s["config"] | {"guard": s["config"]["guard"] | {"max_pages": 30}}
    r = client.put("/api/settings", json={"config": good, "topics": ["books & reading", "music"]})
    assert r.json() == {"saved": True, "topics_changed": True}
    text = config.PATH.read_text()
    assert "max_pages = 30" in text and "# limits for platforms" in text  # comments kept
    assert client.get("/api/settings").json()["topics"] == ["books & reading", "music"]


def test_related_and_item_api(con):
    import numpy as np
    from fastapi.testclient import TestClient
    from savedmap import web
    for n, src in enumerate(["instagram", "instagram", "goodreads", "instagram"]):
        update.store(con, src, Batch(items=[item(n)]), resumed=False)
        v = np.zeros(4, np.float32); v[n % 2] = 1; v[3] = 0.1 * n
        con.execute("INSERT OR REPLACE INTO analysis (item_id, visual_emb, text_emb, summary, tags) VALUES (?,?,?,?,?)",
                    (f"{src}:p{n}", db.to_blob(v), db.to_blob(v), f"summary {n}", '["a"]'))
    con.commit()
    client = TestClient(web.app)
    rel = client.get("/api/related/instagram:p0").json()["results"]
    assert "instagram:p0" not in rel and "goodreads:p2" in rel  # never itself; other platforms get a slot
    det = client.get("/api/item/instagram:p1").json()
    assert det["summary"] == "summary 1" and det["tags"] == ["a"] and det["text"] == "post 1"
    assert client.get("/api/item/nope:x").status_code == 404
    con.execute("UPDATE items SET download_done=1"); con.commit()
    page = client.get("/").text  # first screen inside the page, CSS inlined
    assert '<script id="boot"' in page and '"total":4' in page and '"multi":true' in page
    assert 'href="/static/app.css"' not in page and 'rel="preload" as="image"' not in page  # test items have no thumbs


def test_read_only_copy(con, monkeypatch):
    from fastapi.testclient import TestClient
    from savedmap import web
    monkeypatch.setattr(web, "READ_ONLY", True)
    client = TestClient(web.app)
    assert client.get("/api/update").json()["read_only"] is True
    assert client.post("/api/update").status_code == 403
    assert client.get("/api/settings").status_code == 403
    assert client.put("/api/settings", json={"config": {}, "topics": []}).status_code == 403


def test_after_update_hook(con, monkeypatch, tmp_path):
    hook = tmp_path / "hooks" / "after-update"
    monkeypatch.setattr(update, "HOOK", hook)
    update.after_update()  # no hook: nothing happens
    hook.parent.mkdir()
    hook.write_text(f"#!/bin/sh\necho ran > {tmp_path / 'out'}\n")
    hook.chmod(0o755)
    update.after_update()
    assert (tmp_path / "out").read_text() == "ran\n"
