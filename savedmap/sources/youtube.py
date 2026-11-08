"""YouTube playlists and YouTube Music library, from a Google Takeout export. No login.

Takeout (YouTube and YouTube Music → playlists, music library) gives one CSV per playlist with
video ids and dates, and the music library with title/album/artist. It leaves out Liked videos.
Title, channel and description of new videos are read with yt-dlp *without cookies*, 1.5-3.5 s
apart, cached on disk, at most `max_pages` per run: a big first import arrives in batches that are
stored (and can be processed) while the next batch is looked up. Only the thumbnail is downloaded;
the viewer embeds the player.
File and column names are localized (e.g. "playlist/Cooking - video.csv", "ID video"), so files are
recognised by their shape, not their names.
"""
import csv
import json
import random
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import yt_dlp

from .. import db
from ..config import Config
from .base import Batch, Blocked, Item, Media, Source

YT = "https://www.youtube.com"
VIDEO_ID = re.compile(r"^[\w-]{11}$")


class _Quiet:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def read_export(root: Path, skip: list[str], music: bool) -> tuple[list[tuple[str, str, str]], dict[str, dict]]:
    """[(video id, playlist name, added iso)] from playlist CSVs, and {video id: song row} from the music library."""
    entries, songs = [], {}
    for f in sorted(root.rglob("*.csv")):
        with f.open(newline="", encoding="utf-8-sig") as fh:
            # ids starting with "-" are written as " -abc" (spreadsheet formula guard): strip every cell
            rows = [[c.strip() for c in r] for r in csv.reader(fh)]
        if not rows or len(rows[0]) < 2:
            continue
        header = rows[0]
        if any("Song Title" in h for h in header):
            if music:
                for r in rows[1:]:
                    if r and VIDEO_ID.match(r[0]):
                        songs[r[0]] = dict(zip(header, r))
            continue
        if len(header) == 2 and all(VIDEO_ID.match(r[0]) for r in rows[1:] if r):  # "<playlist> - video.csv"
            name = re.sub(r"\s*-\s*videos?$", "", f.stem, flags=re.I)
            if name.lower() in {s.lower() for s in skip}:
                continue
            entries += [(r[0], name, r[1]) for r in rows[1:] if r]
    return entries, songs


def epoch(iso: str) -> int | None:
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except ValueError:
        return None


def to_item(vid: str, meta: dict | None, lists: list[tuple[str, str]], song: dict | None) -> Item:
    """`meta`: anonymous yt-dlp metadata for new videos ({} = unavailable, None = already stored)."""
    m = meta or {}
    up = m.get("upload_date") or ""
    if song:
        artists = ", ".join(v for k, v in song.items() if k.startswith("Artist Name") and v)
        title, author = song.get("Song Title"), artists or None
        text = f"Song by {artists}" + (f", album {song['Album Title']}" if song.get("Album Title") else "") if meta is not None else None
    else:
        title, author = m.get("title"), m.get("channel")
        text = ((m.get("description") or "").strip() or None) if meta is not None else None
    return Item(
        native_id=vid, kind="video", url=f"{YT}/watch?v={vid}", author=author, title=title, text=text,
        created_at=int(time.mktime(time.strptime(up, "%Y%m%d"))) if len(up) == 8 else None,
        collections=lists, media=[Media(kind="image", url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")],
        details={"duration": m.get("duration"), "views": m.get("view_count"), "album": (song or {}).get("Album Title"),
                 "chapters": [c.get("title") for c in m.get("chapters") or []][:30] or None,
                 "unavailable": meta is not None and not song and not m},
        raw={k: m.get(k) for k in ("id", "title", "channel", "channel_id", "upload_date", "duration", "tags", "categories")}
            if m else (song or {}),
    )


class YouTube(Source):
    name = "youtube"

    def fetch(self, cfg: Config, known: set[str], full: bool, max_pages: int, cursor: str | None = None) -> Batch:
        yc = cfg.sources.youtube
        root = Path(yc.takeout).expanduser()
        entries, songs = read_export(root, yc.skip_playlists, yc.music_library)
        if not entries and not songs:
            raise SystemExit(f"No YouTube playlist CSVs under {root}: export from takeout.google.com "
                             "(YouTube and YouTube Music → playlists, music library) and unpack it there")
        keep = db.DATA_DIR / "imports" / "youtube" / datetime.now().strftime("%Y%m%d")
        if not keep.exists():  # dated copy of the CSVs next to the media
            for f in root.rglob("*.csv"):
                (keep / f.relative_to(root)).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, keep / f.relative_to(root))

        # newest added first; a video in several playlists is one item with several collections
        entries.sort(key=lambda e: e[2], reverse=True)
        order, lists, added = [], {}, {}
        for vid, name, when in entries:
            if vid not in lists:
                order.append(vid)
                lists[vid], added[vid] = [], when
            if (name, name) not in lists[vid]:
                lists[vid].append((name, name))
        for vid in songs:
            if vid not in lists:
                order.append(vid)
                lists[vid] = []
            lists[vid].append(("music-library", "Music library"))

        cache_path = db.DATA_DIR / "imports" / "youtube" / "metadata.json"
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        missing = [v for v in order if v not in known and v not in songs and v not in cache]
        todo = missing[:max_pages]  # the rest comes in the next run (cursor)
        print(f"  {len(order)} videos ({len(songs)} songs), {sum(v not in known for v in order)} new, "
              f"{len(missing)} to look up without login (~{len(missing) * 4.5 / 60:.0f} min), {len(todo)} in this run")
        anon = {"quiet": True, "no_warnings": True, "logger": _Quiet(), "skip_download": True,
                "extractor_args": {"youtube": {"player_skip": ["js"], "skip": ["dash", "hls", "translated_subs"]}}}
        try:
            with yt_dlp.YoutubeDL(anon) as ydl:
                for n, vid in enumerate(todo, 1):
                    try:
                        info = ydl.extract_info(f"{YT}/watch?v={vid}", download=False, process=False) or {}
                        cache[vid] = {k: info.get(k) for k in ("title", "channel", "description", "upload_date", "duration",
                                                              "view_count", "chapters", "tags", "categories", "channel_id")}
                    except yt_dlp.utils.DownloadError as e:
                        if "429" in str(e) or "Too Many Requests" in str(e):
                            raise Blocked(f"YouTube rate-limited the lookups: {str(e)[:120]}")
                        cache[vid] = {}  # deleted or private: kept, marked unavailable
                    if n % 20 == 0:
                        cache_path.write_text(json.dumps(cache))
                    print(f"  details {n}/{len(todo)}", end="\r")
                    time.sleep(random.uniform(1.5, 3.5))
        finally:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache))
        print()
        later = set(missing[len(todo):])
        items = []
        for vid in order:
            if vid in later:  # not looked up yet: stored by a later run, never as "unavailable"
                continue
            meta = None if vid in known else cache.get(vid, {})
            it = to_item(vid, meta, lists[vid], songs.get(vid))
            if vid in added and it.created_at is None:
                it.created_at = epoch(added[vid])
            items.append(it)
        return Batch(items=items, complete=not later, cursor="more" if later else None)
