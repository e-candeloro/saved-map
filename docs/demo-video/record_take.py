"""Headless 1920x1080 recording of one demo take, with the demo-only privacy filter on the API responses.
usage: record_take.py <take> <out_dir>      takes: library, topic, map, search"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8770/"  # a running `savedmap serve`
# What to keep out of the recording, from docs/demo-video/hide.json (gitignored, so a library's private
# topics never land in the repo): {"topics": [...], "collections": "regex", "words": "regex"}.
_HIDE_FILE = Path(__file__).with_name("hide.json")
_hide = json.loads(_HIDE_FILE.read_text()) if _HIDE_FILE.exists() else {}
HIDE_TOPICS = set(_hide.get("topics", []))
HIDE_COLS = re.compile(_hide.get("collections") or r"(?!x)x", re.I)
WORDS = re.compile(_hide.get("words") or r"(?!x)x", re.I)


def filter_data(route):
    r = route.fetch(); d = r.json()
    hidden = {c["id"] for c in d["collections"] if HIDE_COLS.search(c["name"])}
    d["items"] = [p for p in d["items"] if not set(p["topics"]) & HIDE_TOPICS and not set(p["collections"]) & hidden
                  and not WORDS.search(p.get("title") or "") and not WORDS.search(p.get("summary") or "")]
    d["collections"] = [c for c in d["collections"] if c["id"] not in hidden]
    route.fulfill(response=r, json=d)


def filter_layout(route):
    r = route.fetch(); d = r.json()
    for v in d.values():
        v["clusters"] = {k: " · ".join(x for x in lab.split(" · ") if not WORDS.search(x)) for k, lab in v["clusters"].items()}
    route.fulfill(response=r, json=d)


def filter_item(route):
    r = route.fetch(); d = r.json()
    d["tags"] = [t for t in d.get("tags") or [] if not WORDS.search(t)]
    route.fulfill(response=r, json=d)


CLUSTER_JS = """() => {
  // the dense middle of the map: median position of every visible item
  const L = S.layout[S.mode], r = devicePixelRatio || 1, b = document.querySelector('#map').getBoundingClientRect();
  const pts = Object.entries(L.points).filter(([id]) => S.byId[id]).map(([, pt]) => screen(pt));
  const med = a => a.sort((x, y) => x - y)[Math.floor(a.length / 2)];
  return [b.left + med(pts.map(p => p[0])) / r, b.top + med(pts.map(p => p[1])) / r, -99];
}"""
SAFE = ["cooking & recipes", "travel & places", "art & illustration", "fashion & outfits", "books & reading", "tech & ai",
        "graphic design & typography", "architecture & interiors", "photography", "nature & outdoors", "pixel art & game art"]
PICK_JS = """(safe) => {
  const L = S.layout[S.mode], r = devicePixelRatio || 1, b = document.querySelector('#map').getBoundingClientRect();
  const mid = [b.width / 2, b.height / 2];
  let best = null;
  for (const [id, pt] of Object.entries(L.points)) {
    const p = S.byId[id];
    if (!p || !p.thumb || p.kind === 'video' || !(p.title || p.name) || !p.topics.some(t => safe.includes(t))) continue;
    const [x, y] = screen(pt).map(v => v / r);
    if (x < 160 || y < 140 || x > b.width - 260 || y > b.height - 160) continue;
    const d = Math.hypot(x - mid[0], y - mid[1]);
    if (!best || d < best.d) best = { id, title: p.title || p.name, x: b.left + x, y: b.top + y, d };
  }
  return best;
}"""


def zoom_and_pan(pg, wait):
    box = pg.locator("#map").bounding_box()
    pg.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.5)
    wait(400)
    tx, ty, cid = pg.evaluate(CLUSTER_JS)
    pg.mouse.move(tx, ty, steps=22)
    for _ in range(7):  # zoom towards the cluster (about 2.7x)
        pg.mouse.wheel(0, -160)
        wait(110)
    wait(600)
    pg.mouse.down()  # pan the cluster towards the middle of the canvas
    cx, cy = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
    pg.mouse.move(tx + (cx - tx) * 0.6, ty + (cy - ty) * 0.6, steps=28)
    pg.mouse.up()
    wait(700)
    return cid


def take_map(pg, wait):
    """Zoom into the dense middle of the map with the wheel, pan, hover a post or pin, click it, look, close."""
    pg.goto(BASE + "#tab=map")
    pg.wait_for_function("S.items.length > 0 && Object.keys(S.layout).length > 0")
    pg.wait_for_function("document.querySelector('#mapNote').textContent.startsWith('Scroll')", timeout=60000)
    zoom_and_pan(pg, wait)  # rehearsal: loads the zoomed-in thumbnails
    pg.wait_for_function("document.querySelector('#mapNote').textContent.startsWith('Scroll')", timeout=60000)
    pg.evaluate("resetView()")
    wait(1500)
    start = pg.evaluate("performance.now()") / 1000
    wait(600)
    cid = zoom_and_pan(pg, wait)
    pick = pg.evaluate(PICK_JS, SAFE)
    pg.mouse.move(pick["x"], pick["y"], steps=25)
    wait(1400)  # the hover preview shows title + summary
    pg.mouse.click(pick["x"], pick["y"])
    wait(3300)
    pg.keyboard.press("Escape")
    wait(700)
    return start, pick["id"] + " " + pick["title"]


def ready(pg, url):
    pg.goto(url)
    pg.wait_for_function("S.items.length > 0 && Object.keys(S.layout).length > 0")
    pg.wait_for_timeout(1800)


def take_library(pg, wait):
    """Everything, then each platform in turn, back to everything."""
    ready(pg, BASE)
    start = pg.evaluate("performance.now()") / 1000
    wait(1200)
    for src in ("pinterest", "youtube", "goodreads", ""):
        pg.locator(f'#side [data-f="platform"][data-v="{src}"]').click()
        wait(1500)
    return start, ""


def take_topic(pg, wait):
    """The cross-platform books topic, a book, then a related reel from another platform."""
    ready(pg, BASE)
    pg.locator('#side [data-f="topic"][data-v="books & reading"]').click()  # rehearsal loads its thumbnails
    wait(2500)
    pg.locator("#resetFilters").click()
    wait(1200)
    start = pg.evaluate("performance.now()") / 1000
    wait(600)
    pg.locator('#side [data-f="topic"][data-v="books & reading"]').click()
    wait(1800)
    book = pg.locator('#grid [data-id="goodreads:24113"]')  # Gödel, Escher, Bach
    (book if book.count() else pg.locator('#grid [data-id^="goodreads:"]').first).click()
    pg.wait_for_selector("[data-related]")
    wait(2200)
    other = pg.locator('[data-related^="instagram:"], [data-related^="youtube:"], [data-related^="pinterest:"]').first
    other.hover()
    wait(700)
    other.click()
    wait(2600)
    pg.keyboard.press("Escape")
    wait(500)
    return start, ""


def take_search(pg, wait):
    """Search by meaning, open the first result."""
    ready(pg, BASE)
    pg.evaluate("fetch('/api/search?k=120&q=pasta%20recipe')")  # warm the search models
    wait(1500)
    start = pg.evaluate("performance.now()") / 1000
    wait(500)
    pg.locator("#q").click()
    pg.keyboard.type("pasta recipe", delay=85)
    wait(2600)
    pg.locator("#grid [data-id]").first.click()
    pg.wait_for_selector("[data-related]")
    wait(3200)
    pg.keyboard.press("Escape")
    wait(400)
    return start, ""


TAKES = {"library": take_library, "topic": take_topic, "map": None, "search": take_search}


def main():
    take, out_dir = sys.argv[1], sys.argv[2]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, color_scheme="light",
                                  record_video_dir=out_dir, record_video_size={"width": 1920, "height": 1080})
        ctx.route("**/api/data", filter_data)
        ctx.route("**/api/layout", filter_layout)
        ctx.route("**/api/item/**", filter_item)
        pg = ctx.new_page()
        TAKES["map"] = take_map
        start, picked = TAKES[take](pg, pg.wait_for_timeout)
        video = pg.video.path()
        ctx.close()
        browser.close()
    print(json.dumps({"video": str(video), "start": start, "picked": picked}))


if __name__ == "__main__":
    main()
