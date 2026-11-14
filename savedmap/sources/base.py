"""The connector contract: every platform turns its saved things into `Item`s.

A source only fetches. Storing, downloading, processing and the ban guard are shared (update.py).
"""
from typing import Literal

from pydantic import BaseModel, Field

from ..config import Config


class Media(BaseModel):
    kind: Literal["image", "video", "cover"]  # cover: thumbnail/poster, not shown as content or OCR'd
    url: str | None = None   # downloaded by the shared downloader (plain HTTP, no cookies)
    path: str | None = None  # already downloaded by the source, relative to MEDIA_DIR


class Item(BaseModel):
    native_id: str = Field(pattern=r"^[\w.-]+$")  # used in file paths
    kind: Literal["post", "pin", "book", "video", "bookmark"]
    url: str
    author: str | None = None
    title: str | None = None
    text: str | None = None
    created_at: int | None = None
    collections: list[tuple[str, str]] = []  # (native id, name): IG collections, boards, shelves
    media: list[Media] = []
    details: dict = {}  # extras for the viewer: likes, rating, ...
    raw: dict = {}


class Batch(BaseModel):
    items: list[Item]          # newest saved first
    complete: bool = False     # True when this is the whole saved set, so missing items count as removed
    cursor: str | None = None  # set when stopped by max_pages: pass it back to continue with older items


class Blocked(Exception):
    """The platform pushed back (rate limit, login challenge): stop and cool down."""


class NeedsLogin(Exception):
    """No valid session: the user has to run `savedmap connect <source>`."""


class Unavailable(Exception):
    """The source can't be reached or rejects its settings (server off, wrong key): skip it this time."""


class Source:
    name: str
    needs_login: bool = False

    def login(self, cfg: Config) -> None:
        print(f"{self.name} needs no login.")

    def fetch(self, cfg: Config, known: set[str], full: bool, max_pages: int, cursor: str | None = None) -> Batch:
        """Saved items, newest first, at most `max_pages` requests.
        Incremental: stop at the first page whose items are all in `known` (native ids).
        `full`: list everything (lets the caller mark unsaved items as removed).
        `cursor`: continue an earlier run that stopped at max_pages (older items only)."""
        raise NotImplementedError
