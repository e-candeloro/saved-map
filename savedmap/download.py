"""Shared downloader: fetches every media file that has a URL but no local file yet.
Plain HTTP without cookies, a few files in parallel; DB writes stay in the main thread."""
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from . import db

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
       "image/heic": ".heic", "video/mp4": ".mp4"}


def fetch_item(client: httpx.Client, item_id: str, files: list) -> tuple[list[tuple[int, str]], list[int]] | None:
    """Download one item's pending files (no DB access, safe in a thread).
    ([(idx, path)], [idx of files that are gone for good]) or None on a failure worth retrying."""
    folder = db.MEDIA_DIR / db.item_dir(item_id)
    folder.mkdir(parents=True, exist_ok=True)
    done, gone = [], []
    for idx, kind, url in files:
        try:
            r = client.get(url)
        except httpx.HTTPError as e:
            print(f"\n  ! {item_id} file {idx}: {e}")
            return None
        if r.status_code in (404, 410):  # deleted upstream (e.g. a removed YouTube video): don't retry forever
            gone.append(idx)
            continue
        if r.status_code != 200:
            print(f"\n  ! {item_id} file {idx}: HTTP {r.status_code}")
            return None
        ext = EXT.get(r.headers.get("content-type", "").split(";")[0], ".mp4" if kind == "video" else ".jpg")
        name = f"cover{ext}" if kind == "cover" else f"{idx}{ext}"
        (folder / name).write_bytes(r.content)
        done.append((idx, f"{db.item_dir(item_id)}/{name}"))
    return done, gone


def download_all(con, workers: int = 6) -> int:
    """Returns the number of items that failed (their links may have expired)."""
    pending: dict[str, list] = {}
    for r in con.execute("""SELECT m.item_id, m.idx, m.kind, m.url FROM media m JOIN items i ON i.id = m.item_id
                            WHERE i.download_done = 0 AND m.path IS NULL AND m.url IS NOT NULL
                            ORDER BY i.saved_pos, m.idx"""):
        pending.setdefault(r["item_id"], []).append((r["idx"], r["kind"], r["url"]))
    # items whose files are all present (or that have none, like a book without a cover)
    con.execute("""UPDATE items SET download_done = 1 WHERE download_done = 0 AND NOT EXISTS
                   (SELECT 1 FROM media m WHERE m.item_id = items.id AND m.path IS NULL)""")
    con.commit()
    if not pending:
        return 0
    print(f"Downloading {len(pending)} items to {db.MEDIA_DIR}")
    failed = 0
    with httpx.Client(headers={"User-Agent": UA}, timeout=120, follow_redirects=True,
                      limits=httpx.Limits(max_connections=workers)) as client, ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(fetch_item, client, item_id, files): item_id for item_id, files in pending.items()}
        for n, fut in enumerate(as_completed(futures), 1):
            item_id, res = futures[fut], fut.result()
            if res is None:
                failed += 1
            else:
                done, gone = res
                con.executemany("UPDATE media SET path=? WHERE item_id=? AND idx=?", [(p, item_id, i) for i, p in done])
                con.executemany("DELETE FROM media WHERE item_id=? AND idx=?", [(item_id, i) for i in gone])
                con.execute("UPDATE items SET download_done=1 WHERE id=?", (item_id,))
                con.commit()
            print(f"  {n}/{len(pending)}", end="\r")
    print(f"\n{failed} downloads failed" + (" (links expired? the next update refreshes them)" if failed else ""))
    return failed
