"""One-time move from the Instagram-only layout (v0.1: `posts` keyed by shortcode) to the
multi-platform one (v0.2: `items` keyed by "<source>:<native id>", files under <source>/).
Backs up the DB first, checks counts before committing, and is safe to re-run."""
import json
import shutil
import sqlite3
from datetime import datetime

from . import config, db

COPY = """
INSERT INTO items (id, source, native_id, kind, url, author, text, created_at, details, raw, saved_pos, status, download_done, first_seen)
  SELECT 'instagram:'||code, 'instagram', code, 'post', 'https://www.instagram.com/p/'||code||'/', username, caption, taken_at,
         json_object('likes', like_count, 'media_type', media_type), raw, saved_pos, 'active', download_done, first_seen FROM old_posts;
INSERT INTO collections (id, source, name, url) SELECT 'instagram:'||id, 'instagram', name, url FROM old_collections;
INSERT INTO memberships SELECT 'instagram:'||collection_id, 'instagram:'||code FROM old_memberships;
INSERT INTO media (item_id, idx, kind, path) SELECT 'instagram:'||code, idx, kind, 'instagram/'||path FROM old_media;
INSERT INTO analysis (item_id, transcript, language, ocr, visual_emb, text_emb, title, summary, tags)
  SELECT 'instagram:'||code, transcript, language, ocr, visual_emb, text_emb, title, summary, tags FROM old_analysis;
"""
TABLES = [("posts", "items"), ("collections", "collections"), ("memberships", "memberships"),
          ("media", "media"), ("analysis", "analysis")]


def migrate_db() -> None:
    con = sqlite3.connect(db.DB_PATH)
    con.row_factory = sqlite3.Row
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='posts'").fetchone():
        print("Database already migrated.")
        return
    backup = db.DB_PATH.with_name(f"savedmap.db.bak-{datetime.now():%Y%m%d-%H%M}")
    with sqlite3.connect(backup) as dst:
        con.backup(dst)
    print("Backup:", backup)
    user = con.execute("SELECT value FROM meta WHERE key='user'").fetchone()
    first_sync = con.execute("SELECT MAX(first_seen) FROM posts").fetchone()[0]

    renames = "".join(f"ALTER TABLE {t} RENAME TO old_{t};\n" for t, _ in TABLES)
    con.executescript("BEGIN;\n" + renames + db.SCHEMA + COPY)  # transaction left open for the checks below
    for old, new in TABLES:
        a = con.execute(f"SELECT COUNT(*) FROM old_{old}").fetchone()[0]
        b = con.execute(f"SELECT COUNT(*) FROM {new}").fetchone()[0]
        print(f"  {old}: {a} -> {new}: {b}")
        if a != b:
            con.rollback()
            raise SystemExit(f"Count mismatch in {old}; nothing changed (backup at {backup}).")
    con.execute("INSERT OR REPLACE INTO meta VALUES ('sync:instagram:last', ?)", (str(first_sync),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('sync:instagram:last_full', ?)", (str(first_sync),))
    con.execute("DELETE FROM meta WHERE key='user'")
    con.commit()
    con.executescript("".join(f"DROP TABLE old_{t};\n" for t, _ in TABLES) + "VACUUM;")
    con.close()

    if not config.PATH.exists():
        text = config.TEMPLATE.replace('[sources.instagram]\nenabled = false\nuser = ""',
                                       f'[sources.instagram]\nenabled = true\nuser = "{user[0] if user else ""}"')
        config.PATH.write_text(text)
        print("Wrote", config.PATH)


def move_files() -> None:
    """media/<code>/ -> media/instagram/<code>/, same for frames/ and thumbs/<code>.jpg (idempotent)."""
    moved = 0
    for base in (db.MEDIA_DIR, db.FRAMES_DIR, db.THUMB_DIR):
        if not base.exists():
            continue
        dest = base / "instagram"
        dest.mkdir(exist_ok=True)
        for p in base.iterdir():
            if p.name in ("instagram", "pinterest", "goodreads"):
                continue
            shutil.move(p, dest / p.name)
            moved += 1
    print(f"Moved {moved} folders/files under instagram/")


def fix_layout() -> None:
    path = db.DATA_DIR / "layout.json"
    if not path.exists():
        return
    layout = json.loads(path.read_text())
    for view in layout.values():
        view["points"] = {(k if ":" in k else f"instagram:{k}"): v for k, v in view["points"].items()}
    path.write_text(json.dumps(layout))


def run() -> None:
    migrate_db()
    move_files()
    fix_layout()
    print("Migration done.")
