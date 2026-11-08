"""Goodreads books, from the library CSV export (My Books → Tools → Import and export).

Goodreads retired its API in 2020 and, by late 2026, also its public shelf RSS feeds; shelf pages
need a login. The CSV is official, complete and needs no login, so this source never touches your
account. Updates: export again; the newest export in the configured folder is picked up, and a
dated copy of each one is kept in <data>/imports/goodreads/.
Covers and subjects come from Open Library's public API, once per new book, about 1 request/s.
"""
import csv
import glob
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import httpx

from .. import db
from ..config import Config
from .base import Batch, Item, Media, Source

GR = "https://www.goodreads.com"
OPEN_LIBRARY = "https://openlibrary.org/search.json"
UA = "SavedMap/0.2 (personal library tool)"


def newest_export(pattern: str) -> Path | None:
    files = glob.glob(str(Path(pattern).expanduser()))
    return Path(max(files, key=lambda f: Path(f).stat().st_mtime)) if files else None


def clean_isbn(s: str) -> str:
    return "".join(ch for ch in s or "" if ch.isdigit() or ch == "X")  # CSV wraps them as ="0451526538"


def epoch(date: str) -> int | None:
    try:
        return int(datetime.strptime(date, "%Y/%m/%d").timestamp())
    except ValueError:
        return None


def to_item(row: dict, extra: dict | None) -> Item:
    """One CSV row. `extra` (Open Library cover + subjects) only for books not stored yet; for known
    books text and media stay as stored."""
    shelves = [row["Exclusive Shelf"]] + [s.strip() for s in (row.get("Bookshelves") or "").split(",") if s.strip()]
    shelves = list(dict.fromkeys(s for s in shelves if s))
    review = (row.get("My Review") or "").replace("<br/>", "\n").strip()
    text = None
    if extra is not None:
        subjects = ", ".join(extra.get("subject", [])[:12])
        text = "\n".join(p for p in [review, f"Subjects: {subjects}" if subjects else ""] if p)
    cover = f"https://covers.openlibrary.org/b/id/{extra['cover_i']}-L.jpg" if extra and extra.get("cover_i") else None
    return Item(
        native_id=row["Book Id"], kind="book", url=f"{GR}/book/show/{row['Book Id']}",
        author=row["Author"], title=row["Title"], text=text, created_at=epoch(row.get("Date Added", "")),
        collections=[(s, s.replace("-", " ").capitalize()) for s in shelves],
        media=[Media(kind="cover", url=cover)] if cover else [],
        details={"rating": int(float(row.get("My Rating") or 0)) or None, "avg_rating": row.get("Average Rating") or None,
                 "year": row.get("Original Publication Year") or row.get("Year Published"),
                 "pages": row.get("Number of Pages"), "date_read": row.get("Date Read"),
                 "isbn": clean_isbn(row.get("ISBN13") or row.get("ISBN")), "review": review or None},
        raw=row,
    )


def open_library(client: httpx.Client, row: dict) -> dict:
    """Best match on Open Library: by ISBN, else title + author. {} when nothing is found."""
    isbn = clean_isbn(row.get("ISBN13")) or clean_isbn(row.get("ISBN"))
    title = row["Title"].split("(")[0].strip()  # drop series info like "(Dune #1)"
    queries = ([{"isbn": isbn}] if isbn else []) + [{"title": title, "author": row["Author"]}]
    for q in queries:
        try:
            r = client.get(OPEN_LIBRARY, params={**q, "fields": "cover_i,subject,first_publish_year", "limit": 1})
            docs = r.json().get("docs", []) if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            docs = []
        time.sleep(1)  # be polite to a free public service
        if docs:
            return docs[0]
    return {}


class Goodreads(Source):
    name = "goodreads"

    def fetch(self, cfg: Config, known: set[str], full: bool, max_pages: int, cursor: str | None = None) -> Batch:
        path = newest_export(cfg.sources.goodreads.export_csv)
        if not path:
            raise SystemExit(f"No Goodreads export matching {cfg.sources.goodreads.export_csv}: export it from "
                             "goodreads.com → My Books → Tools → Import and export")
        keep = db.DATA_DIR / "imports" / "goodreads" / f"{path.stem}-{datetime.fromtimestamp(path.stat().st_mtime):%Y%m%d-%H%M}.csv"
        if not keep.exists():  # a dated copy of every export next to the media, in case Downloads gets cleaned
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, keep)
        with path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        rows.sort(key=lambda r: r.get("Date Added") or "", reverse=True)  # newest saved first
        new = [r for r in rows if r["Book Id"] not in known]
        print(f"  {path.name}: {len(rows)} books, {len(new)} new" + (" (looking up covers on Open Library)" if new else ""))
        cache_path = db.DATA_DIR / "imports" / "goodreads" / "openlibrary.json"  # lookups survive a failed run
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        with httpx.Client(headers={"User-Agent": UA}, timeout=30) as client:
            for n, r in enumerate(new, 1):
                if r["Book Id"] not in cache:
                    cache[r["Book Id"]] = open_library(client, r)
                    if n % 20 == 0:
                        cache_path.write_text(json.dumps(cache))
                print(f"  covers {n}/{len(new)}", end="\r")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
        extra = {r["Book Id"]: cache[r["Book Id"]] for r in new}
        return Batch(items=[to_item(r, extra.get(r["Book Id"])) for r in rows], complete=True)
