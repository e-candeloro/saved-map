"""Karakeep bookmarks, from your own server's REST API with an API key (Settings → API Keys).

Your server, your key: no platform account is involved, so the ban guard doesn't apply. Every update
reads the whole list (100 bookmarks per request), which also notices deleted bookmarks; the dry run reads
one page. Lists become collections. Pictures are the ones Karakeep's crawler already stored (the page's
banner image, else its screenshot), fetched through short-lived signed links, so the shared downloader
never needs the key and nothing is requested from the bookmarked sites.
"""
import os
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from ..config import Config
from .base import Batch, Item, Media, Source, Unavailable

PAGE = 100


def epoch(iso: str | None) -> int | None:
    try:
        return int(datetime.fromisoformat(iso).timestamp()) if iso else None
    except ValueError:
        return None


def picture(b: dict) -> str | None:
    """Id of the stored asset that best pictures this bookmark."""
    c = b["content"]
    if c.get("type") == "link":
        return c.get("imageAssetId") or c.get("screenshotAssetId")
    if c.get("type") == "asset":
        if c.get("assetType") == "image":
            return c.get("assetId")
        return next((a["id"] for a in b.get("assets", []) if a["assetType"] == "assetScreenshot"), None)
    return None


def to_item(b: dict, base: str, lists: list[tuple[str, str]], image_url: str | None) -> Item:
    c, kind = b["content"], b["content"].get("type")
    link = c.get("url") if kind == "link" else c.get("sourceUrl")
    title = b.get("title") or c.get("title") or c.get("fileName")
    body = {"link": c.get("description"), "text": c.get("text"), "asset": (c.get("content") or "")[:4000]}.get(kind)
    if kind == "text" and not title and body:
        title = body.strip().split("\n")[0][:120]
    tags = [t["name"] for t in b.get("tags", [])]
    text = "\n\n".join(p for p in [body, b.get("note"), b.get("summary"), f"Tags: {', '.join(tags)}" if tags else ""] if p)
    return Item(
        native_id=b["id"], kind="bookmark", url=f"{base}/dashboard/preview/{b['id']}", title=title,
        author=c.get("author") or c.get("publisher"), text=text or None, created_at=epoch(b.get("createdAt")),
        collections=lists, media=[Media(kind="image", url=image_url)] if image_url else [],
        details={"link": link, "domain": urlsplit(link).hostname if link else None, "tags": tags,
                 "favourite": b.get("favourited") or None, "archived": b.get("archived") or None},
        raw={k: b.get(k) for k in ("id", "createdAt", "title", "note", "archived", "favourited")},
    )


class Karakeep(Source):
    name = "karakeep"

    def fetch(self, cfg: Config, known: set[str], full: bool, max_pages: int, cursor: str | None = None) -> Batch:
        kc = cfg.sources.karakeep
        base = kc.url.rstrip("/")
        key = os.environ.get(kc.api_key_env)
        if not base or not key:
            raise Unavailable(f"set url in [sources.karakeep] and the environment variable {kc.api_key_env}")
        dry_run = max_pages == 1  # the dry run's single request; otherwise it's your own server, so read it all
        with httpx.Client(base_url=f"{base}/api/v1", headers={"Authorization": f"Bearer {key}"}, timeout=60) as api:
            def get(path: str, **params) -> dict:
                try:
                    r = api.get(path, params={k: v for k, v in params.items() if v is not None})
                except httpx.HTTPError as e:
                    raise Unavailable(f"can't reach Karakeep at {base}: {e}") from e
                if r.status_code == 401:
                    raise Unavailable(f"Karakeep rejected the key in {kc.api_key_env}")
                r.raise_for_status()
                return r.json()

            def pages(path: str):
                nxt = None
                while True:
                    page = get(path, limit=PAGE, cursor=nxt, includeContent="false")
                    yield page["bookmarks"]
                    nxt = page.get("nextCursor")
                    if not nxt or dry_run:
                        return

            bookmarks = [b for page in pages("/bookmarks") for b in page]
            if dry_run:
                return Batch(items=[to_item(b, base, [], None) for b in bookmarks])
            member: dict[str, list[tuple[str, str]]] = {}
            for lst in get("/lists")["lists"]:
                if lst.get("type", "manual") == "manual":
                    for page in pages(f"/lists/{lst['id']}/bookmarks"):
                        for b in page:
                            member.setdefault(b["id"], []).append((lst["id"], lst["name"]))
            items = []
            for n, b in enumerate(bookmarks, 1):
                url = None
                if b["id"] not in known and (asset := picture(b)):
                    signed = get(f"/assets/{asset}/signed-url")["signedUrl"]
                    p = urlsplit(signed)  # the server may sign with its internal address: keep only path + query
                    url = f"{base}{p.path}" + (f"?{p.query}" if p.query else "")
                    print(f"  pictures {n}/{len(bookmarks)}", end="\r")
                items.append(to_item(b, base, member.get(b["id"], []), url))
        print(f"  {len(items)} bookmarks, {sum(b['id'] not in known for b in bookmarks)} new")
        return Batch(items=items, complete=True)
