"""Instagram saved posts.

Instagram has no public API for saved posts. A real Chrome window (dedicated profile, logged in
once) opens your saved page normally, then pages through the same saved-feed endpoint the web app
uses: ~21 posts per request with captions, collections and full media links, a few seconds apart.
Media is then downloaded from the CDN by the shared downloader, without cookies.
"""
import json
import random
import re

from playwright.sync_api import Page, sync_playwright

from .. import browser
from ..config import Config
from .base import Batch, Blocked, Item, Media, NeedsLogin, Source

IG = "https://www.instagram.com"
WEB_APP_ID = "936619743392459"  # Instagram web app id, sent by instagram.com itself

FETCH_PAGE = """async ([appId, maxId]) => {
    const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1];
    const url = '/api/v1/feed/saved/posts/' + (maxId ? '?max_id=' + encodeURIComponent(maxId) : '');
    const r = await fetch(url, {credentials: 'include', headers: {
        'x-ig-app-id': appId, 'x-csrftoken': csrf, 'x-requested-with': 'XMLHttpRequest'}});
    return {status: r.status, body: await r.text()};
}"""


def rnd(a: float, b: float) -> float:
    return random.uniform(a, b)


def collection_names(page: Page, user: str) -> dict[str, str]:
    """{collection id: name} from the tiles on the saved page (already loaded, no extra requests)."""
    tiles = page.eval_on_selector_all(
        f'a[href^="/{user}/saved/"]', "els => els.map(e => [e.getAttribute('href'), e.innerText])")
    names = {}
    for href, text in tiles:
        m = re.fullmatch(rf"/{re.escape(user)}/saved/([^/]+)/(\d+)/?", href)
        if m:
            slug, cid = m.groups()
            names[cid] = (text or "").strip().split("\n")[0] or slug.replace("-", " ").title()
    return names


def media_items(node: dict) -> list[Media]:
    def best_img(n):
        c = (n.get("image_versions2") or {}).get("candidates") or []
        return max(c, key=lambda x: x.get("width", 0))["url"] if c else None

    def best_vid(n):
        v = n.get("video_versions") or []
        return max(v, key=lambda x: (x.get("height", 0), x.get("bandwidth", 0)))["url"] if v else None

    out = []
    for it in node.get("carousel_media") or [node]:
        if best_vid(it):
            out.append(Media(kind="video", url=best_vid(it)))
        elif best_img(it):
            out.append(Media(kind="image", url=best_img(it)))
    if not node.get("carousel_media") and best_vid(node) and best_img(node):
        out.append(Media(kind="cover", url=best_img(node)))
    return out


def to_item(node: dict, names: dict[str, str]) -> Item:
    return Item(
        native_id=node["code"], kind="post", url=f"{IG}/p/{node['code']}/",
        author=(node.get("user") or {}).get("username"), text=(node.get("caption") or {}).get("text"),
        created_at=node.get("taken_at"),
        collections=[(cid, names.get(cid, "")) for cid in node.get("saved_collection_ids") or []],
        media=media_items(node),
        details={"likes": node.get("like_count"), "media_type": node.get("media_type")},
        raw=node,
    )


class Instagram(Source):
    name = "instagram"
    needs_login = True

    def login(self, cfg: Config) -> None:
        browser.wait_for_login(f"{IG}/accounts/login/", "sessionid")

    def fetch(self, cfg: Config, known: set[str], full: bool, max_pages: int, cursor: str | None = None) -> Batch:
        user = cfg.sources.instagram.user
        if not user:
            raise SystemExit("Set [sources.instagram] user in config.toml")
        nodes, complete, next_cursor = [], False, None
        with sync_playwright() as p:
            ctx = browser.open_browser(p)
            try:
                if not browser.has_cookie(ctx, IG, "sessionid"):
                    raise NeedsLogin("Not logged in to Instagram: run `savedmap connect instagram`")
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(f"{IG}/{user}/saved/", wait_until="domcontentloaded")
                page.wait_for_timeout(rnd(4000, 6000))
                if "/accounts/login" in page.url or "/challenge" in page.url:
                    raise NeedsLogin(f"Instagram asked to log in again ({page.url}): run `savedmap connect instagram`")
                for _ in range(4):  # collection tiles below the fold only render after scrolling
                    page.mouse.wheel(0, rnd(400, 800))
                    page.wait_for_timeout(rnd(800, 1600))
                names = collection_names(page, user)

                max_id, pages = cursor, 0
                while True:
                    res = page.evaluate(FETCH_PAGE, [WEB_APP_ID, max_id])
                    pages += 1
                    if res["status"] != 200:
                        raise Blocked(f"Instagram answered HTTP {res['status']} on page {pages}: {res['body'][:160]}")
                    d = json.loads(res["body"])
                    batch = [it.get("media", it) for it in d.get("items", [])]
                    nodes += batch
                    print(f"  page {pages}: {len(nodes)} posts", end="\r")
                    if not d.get("more_available"):
                        complete = cursor is None and (full or not known)
                        break
                    if not full and cursor is None and batch and all(m["code"] in known for m in batch):
                        break
                    max_id = d.get("next_max_id")
                    if pages >= max_pages:
                        next_cursor = max_id
                        print(f"\n  stopped after {max_pages} pages")
                        break
                    page.wait_for_timeout(rnd(3000, 8000))
                    if pages % random.randint(20, 30) == 0:
                        page.wait_for_timeout(rnd(20000, 45000))  # occasional longer break
            finally:
                ctx.close()
        print()
        return Batch(items=[to_item(n, names) for n in nodes], complete=complete, cursor=next_cursor)
