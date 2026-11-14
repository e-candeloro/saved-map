"""`savedmap update`: fetch only what's new from every enabled platform, store it, download,
process, refine and re-cluster. The ban guard lives here, once, for every source that needs a login."""
import json
import os
import subprocess
import time
from datetime import datetime

from . import config, db
from .config import Config
from .sources import SOURCES
from .sources.base import Batch, Blocked, NeedsLogin, Source, Unavailable


def _t(con, name, key) -> float:
    return float(db.get_meta(con, f"sync:{name}:{key}", 0) or 0)


def when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%a %d %b %H:%M")


def status(con, cfg: Config) -> list[dict]:
    """Per enabled source: last sync, whether a sync is allowed now, and why not."""
    out = []
    for name, src in SOURCES.items():
        if not getattr(cfg.sources, name).enabled:
            continue
        reason, next_at = blocked_reason(con, cfg, src, full=False)
        out.append({"source": name, "last": _t(con, name, "last") or None, "allowed": reason is None,
                    "reason": reason, "next": next_at, "count": con.execute(
                        "SELECT COUNT(*) FROM items WHERE source=? AND status='active'", (name,)).fetchone()[0]})
    return out


def blocked_reason(con, cfg: Config, src: Source, full: bool, now: float | None = None,
                   force: bool = False) -> tuple[str | None, float | None]:
    """(why a sync is not allowed now, when it will be) or (None, None). Only login platforms are limited.
    `force` skips the waiting intervals, never the cooldown after the platform pushed back."""
    if not src.needs_login:
        return None, None
    now, g, name = now or time.time(), cfg.guard, src.name
    cooldown = _t(con, name, "cooldown_until")
    if now < cooldown:
        why = db.get_meta(con, f"sync:{name}:cooldown_reason", "")
        return f"Paused until {when(cooldown)} because {name} pushed back: {why}", cooldown
    if force:
        return None, None
    nxt = _t(con, name, "last") + g.min_hours_between_syncs * 3600
    if now < nxt:
        return f"Synced recently; next {name} sync allowed {when(nxt)}", nxt
    if full:
        nxt = _t(con, name, "last_full") + g.full_sync_min_days * 86400
        if now < nxt:
            return f"Full {name} sync allowed once every {g.full_sync_min_days:g} days; next {when(nxt)}", nxt
    return None, None


def store(con, name: str, batch: Batch, resumed: bool) -> int:
    """Upsert a fetched batch; returns the number of new items."""
    known = {r["id"]: r["download_done"] for r in con.execute("SELECT id, download_done FROM items WHERE source=?", (name,))}
    lo, hi = con.execute("SELECT MIN(saved_pos), MAX(saved_pos) FROM items WHERE source=?", (name,)).fetchone()
    # positions: a complete list renumbers everything; new saves go before the known ones; a resumed
    # run (older items) goes after them
    base = 0 if batch.complete else (hi or 0) + 1 if resumed else (lo or 0) - len(batch.items)
    new = 0
    for i, it in enumerate(batch.items):
        iid = f"{name}:{it.native_id}"
        is_new = iid not in known
        new += is_new
        con.execute(
            """INSERT INTO items (id, source, native_id, kind, url, author, title, text, created_at, details, raw, saved_pos)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET url=excluded.url, author=COALESCE(excluded.author, author),
                 title=COALESCE(excluded.title, title), text=COALESCE(excluded.text, text),
                 created_at=COALESCE(excluded.created_at, created_at), details=excluded.details, raw=excluded.raw,
                 status='active', removed_at=NULL""",
            (iid, name, it.native_id, it.kind, it.url, it.author, it.title, it.text, it.created_at,
             json.dumps(it.details), json.dumps(it.raw), base + i))
        if batch.complete:
            con.execute("UPDATE items SET saved_pos=? WHERE id=?", (base + i, iid))
        con.execute("DELETE FROM memberships WHERE item_id=?", (iid,))
        for cid, cname in it.collections:
            con.execute("""INSERT INTO collections (id, source, name) VALUES (?,?,?)
                           ON CONFLICT(id) DO UPDATE SET name=COALESCE(NULLIF(excluded.name, ''), name)""",
                        (f"{name}:{cid}", name, cname))
            con.execute("INSERT OR IGNORE INTO memberships VALUES (?,?)", (f"{name}:{cid}", iid))
        if is_new or (not known[iid] and it.media):  # fresh links for anything not downloaded yet (signed URLs expire)
            con.execute("DELETE FROM media WHERE item_id=?", (iid,))
            con.executemany("INSERT INTO media (item_id, idx, kind, path, url) VALUES (?,?,?,?,?)",
                            [(iid, k, m.kind, m.path, m.url) for k, m in enumerate(it.media)])
            con.execute("UPDATE items SET download_done=0 WHERE id=?", (iid,))
    if batch.complete:
        ids = [f"{name}:{it.native_id}" for it in batch.items]
        con.execute(f"""UPDATE items SET status='removed', removed_at=? WHERE source=? AND status='active'
                        AND id NOT IN ({','.join('?' * len(ids))})""", (int(time.time()), name, *ids))
    con.commit()
    return new


def sync_source(con, cfg: Config, src: Source, full: bool, dry_run: bool, force: bool = False) -> int:
    name = src.name
    reason, _ = blocked_reason(con, cfg, src, full, force=force)
    if reason:
        print(f"[{name}] skipped. {reason}")
        return 0
    cursor = db.get_meta(con, f"sync:{name}:cursor") or None
    first = not con.execute("SELECT 1 FROM items WHERE source=? LIMIT 1", (name,)).fetchone()
    max_pages = 1 if dry_run else cfg.guard.max_pages_full if (full or first or cursor) else cfg.guard.max_pages
    known = {r[0] for r in con.execute("SELECT native_id FROM items WHERE source=?", (name,))}
    print(f"[{name}] {'dry run, 1 request' if dry_run else 'continuing an earlier sync' if cursor else 'full sync' if full else 'checking for new saves'}")
    now = time.time()
    if not dry_run:  # counted before the requests: a crashed run still respects the interval
        db.set_meta(con, f"sync:{name}:last", now)
        con.commit()
    try:
        batch = src.fetch(cfg, known, full, max_pages, None if (full or dry_run) else cursor)
    except Blocked as e:
        db.set_meta(con, f"sync:{name}:cooldown_until", now + cfg.guard.cooldown_hours * 3600)
        db.set_meta(con, f"sync:{name}:cooldown_reason", str(e))
        con.commit()
        print(f"[{name}] stopped: {e}\n  Paused for {cfg.guard.cooldown_hours:g} h. Open the platform in a normal browser "
              f"to check the account, and `savedmap connect {name}` if it asks to log in again.")
        return 0
    except (NeedsLogin, Unavailable) as e:
        print(f"[{name}] {e}")
        return 0
    new = sum(it.native_id not in known for it in batch.items)
    if dry_run:
        print(f"[{name}] OK: first page has {len(batch.items)} items, {new} of them new. Nothing stored.")
        return 0
    added = store(con, name, batch, resumed=bool(cursor) and not full)
    db.set_meta(con, f"sync:{name}:cursor", batch.cursor or "")
    if full:
        db.set_meta(con, f"sync:{name}:last_full", now)
    con.commit()
    removed = con.execute("SELECT COUNT(*) FROM items WHERE source=? AND status='removed' AND removed_at>=?",
                          (name, int(now))).fetchone()[0]
    print(f"[{name}] {added} new" + (f", {removed} no longer saved" if removed else "")
          + (" (more to fetch: run update again later)" if batch.cursor else ""))
    return added


def run(only: list[str] | None = None, full: bool = False, dry_run: bool = False, process_after: bool = True,
        force: bool = False):
    cfg = config.load()
    con = db.connect()
    names = only or [n for n in SOURCES if getattr(cfg.sources, n).enabled]
    if not names:
        raise SystemExit(f"No platform enabled: run `savedmap init` and edit {config.PATH}")
    for name in names:  # one at a time, never in parallel
        if name not in SOURCES:
            raise SystemExit(f"Unknown source {name}; known: {', '.join(SOURCES)}")
        sync_source(con, cfg, SOURCES[name], full, dry_run, force)
    if dry_run:
        return
    from . import download
    download.download_all(con)
    if process_after:
        from . import cluster, process, refine
        process.run()
        refine.run()
        cluster.run(only_if_changed=True)
    print("Update finished.")
    after_update()


HOOK = db.DATA_DIR / "hooks" / "after-update"


def after_update():
    """Run <data folder>/hooks/after-update if it exists and is executable, like a git hook: e.g. copy the
    library to a server. It lives in the data folder, so the web app can't change it. Its failure is reported,
    not fatal: the update itself went fine."""
    if not os.access(HOOK, os.X_OK):
        return
    print(f"Running {HOOK}")
    code = subprocess.run([str(HOOK)], cwd=db.DATA_DIR).returncode
    if code:
        print(f"Warning: {HOOK.name} exited with {code}")
