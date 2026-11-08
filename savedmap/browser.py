"""The dedicated Chrome profile used for platforms that need your login (gitignored, never shared)."""
import time
from pathlib import Path

from playwright.sync_api import BrowserContext

from . import db

PROFILE_DIR = db.ROOT / "browser-profile"


def open_browser(p) -> BrowserContext:
    return p.chromium.launch_persistent_context(
        PROFILE_DIR, channel="chrome", headless=False, viewport={"width": 1280, "height": 900})


def has_cookie(ctx: BrowserContext, url: str, name: str, value: str | None = None) -> bool:
    """True when the session cookie is set (and has `value`, for sites that set it while logged out too)."""
    return any(c["name"] == name and (value is None or c["value"] == value) for c in ctx.cookies(url))


def wait_for_login(url: str, cookie: str, value: str | None = None) -> None:
    """Open `url` in the profile and wait until the user has logged in (the session cookie appears)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = open_browser(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url)
        if not has_cookie(ctx, url, cookie, value):
            print("Log in in the Chrome window. It closes by itself once you're in.")
            while not has_cookie(ctx, url, cookie, value):
                time.sleep(2)
            time.sleep(5)  # let the post-login redirects and cookies settle
        ctx.close()
    print("Logged in; session saved in", PROFILE_DIR)


def cookies_txt(url: str, out: Path) -> bool:
    """Export the profile's cookies for `url` in Netscape format (for gallery-dl). False if none."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=True)
        cookies = ctx.cookies(url)
        ctx.close()
    if not cookies:
        return False
    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        domain = c["domain"]
        lines.append("\t".join([domain, "TRUE" if domain.startswith(".") else "FALSE", c["path"],
                                "TRUE" if c["secure"] else "FALSE", str(int(max(c["expires"], 0))), c["name"], c["value"]]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.touch(mode=0o600)
    out.write_text("\n".join(lines) + "\n")
    return True
