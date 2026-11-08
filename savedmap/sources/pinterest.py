"""Pinterest boards and their pins, through gallery-dl's Pinterest web-API client.

Public boards need no login at all. With `login = true` (after `savedmap connect pinterest`), the
dedicated Chrome profile's cookies are exported for gallery-dl so secret boards are included.
Requests are 2-6 s apart. Boards come sorted by the last pin added, so an incremental sync stops
at the first board whose newest pins are all known. Files are downloaded by the shared downloader.
"""
import itertools
from email.utils import parsedate_to_datetime

from gallery_dl import config as gdl_config
from gallery_dl import exception, extractor

from .. import browser, db
from ..config import Config
from .base import Batch, Blocked, Item, Media, NeedsLogin, Source

PIN = "https://www.pinterest.com"
COOKIES = db.DATA_DIR / "pinterest-cookies.txt"  # in the data folder, never in the repo
PAGE = 25  # pins per API page


class _Cap(Exception):
    pass


def media_of(p: dict) -> list[Media]:
    orig = ((p.get("images") or {}).get("orig") or {}).get("url")
    if car := (p.get("carousel_data") or {}).get("carousel_slots"):
        urls = [((s.get("images") or {}).get("orig") or {}).get("url") or (s.get("images") or {}).get("736x", {}).get("url") for s in car]
        if urls := [u for u in urls if u]:
            return [Media(kind="image", url=u) for u in urls]
    videos = ((p.get("videos") or {}).get("video_list") or {}).values()
    mp4 = [v for v in videos if (v.get("url") or "").endswith(".mp4")]  # skip HLS playlists
    if mp4:
        best = max(mp4, key=lambda v: v.get("width", 0))
        return [Media(kind="video", url=best["url"])] + ([Media(kind="cover", url=orig)] if orig else [])
    return [Media(kind="image", url=orig)] if orig else []


def to_item(p: dict) -> Item:
    created = None
    if p.get("created_at"):
        try:
            created = int(parsedate_to_datetime(p["created_at"]).timestamp())
        except (TypeError, ValueError):
            pass
    text = "\n".join(t for t in [(p.get("description") or "").strip(), (p.get("auto_alt_text") or "").strip()] if t)
    creator = (p.get("native_creator") or {}).get("username")
    return Item(
        native_id=p.get("image_signature") or p["id"],  # stable with or without login, unlike the pin id
        kind="pin", url=PIN + (p.get("seo_url") or f"/pin/{p['id']}/"),
        author=creator or p.get("domain") or None, title=(p.get("title") or p.get("grid_title") or "").strip() or None,
        text=text or None, created_at=created, media=media_of(p),
        details={"link": p.get("link") or None, "domain": p.get("domain") or None},
        raw=p,
    )


class Pinterest(Source):
    name = "pinterest"
    needs_login = True  # rate-limited like a login platform even when reading public boards

    def login(self, cfg: Config) -> None:
        browser.wait_for_login(f"{PIN}/login/", "_auth", "1")  # Pinterest sets _auth=0 when logged out

    def fetch(self, cfg: Config, known: set[str], full: bool, max_pages: int, cursor: str | None = None) -> Batch:
        pc = cfg.sources.pinterest
        if not pc.user:
            raise SystemExit("Set [sources.pinterest] user in config.toml")
        gdl_config.clear()
        gdl_config.set(("extractor",), "sleep-request", [2.0, 6.0])
        if pc.login:
            if not browser.cookies_txt(PIN, COOKIES) or "_auth\t1" not in COOKIES.read_text():
                raise NeedsLogin("Not logged in to Pinterest: run `savedmap connect pinterest`")
            gdl_config.set(("extractor", "pinterest"), "cookies", str(COOKIES))
        ex = extractor.find(f"{PIN}/{pc.user}/")
        ex.initialize()
        api, calls, call = ex.api, [0], ex.api._call

        def counted(resource, options):
            if calls[0] >= max_pages:
                raise _Cap
            calls[0] += 1
            print(f"  request {calls[0]}", end="\r")
            return call(resource, options)
        api._call = counted

        items: dict[str, Item] = {}
        complete = True

        def board_pins(b):
            yield from api.board_pins(b["id"])
            if b.get("section_count"):
                for s in api.board_sections(b["id"]):
                    yield from api.board_section_pins(s["id"])

        try:
            for b in api.boards(pc.user):
                if b.get("type") != "board":  # "All Pins" and suggestion stories
                    continue
                streak = new = 0
                for p in board_pins(b):
                    if p.get("type") != "pin":
                        continue
                    it = to_item(p)
                    it = items.setdefault(it.native_id, it)
                    if (b["id"], b["name"]) not in it.collections:
                        it.collections.append((b["id"], b["name"]))
                    if it.native_id in known:
                        streak += 1
                    else:
                        streak, new = 0, new + 1
                    if not full and streak >= PAGE:  # a whole page already stored: nothing newer in this board
                        complete = False
                        break
                if not full and streak and not new:  # boards are sorted by last pin added: the rest has nothing new
                    complete = False
                    break
        except _Cap:
            complete = False
            print(f"\n  stopped after {max_pages} requests")
        except exception.NotFoundError:
            raise SystemExit(f"Pinterest user {pc.user!r} not found")
        except exception.GalleryDLException as e:
            raise Blocked(f"Pinterest API request failed ({e.__class__.__name__}: {e})")
        print()
        return Batch(items=list(items.values()), complete=complete)
