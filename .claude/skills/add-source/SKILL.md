---
name: add-source
description: Add a new platform connector to SavedMap (e.g. Karakeep, YouTube Watch Later, Reddit saved). Explains the Source contract, the safe ways to fetch, tests with recorded fixtures, and the connect skill to write. Use when someone wants SavedMap to import from a platform it doesn't support yet.
---

# Add a source to SavedMap

A source only fetches. Storage, downloads, processing, the map and the ban guard are shared code in `savedmap/update.py`, `download.py`, `process.py` and the rest. Read `docs/DESIGN.md` first, then one of the existing sources:

| Source | Read it when the new platform… |
| --- | --- |
| `savedmap/sources/goodreads.py` | has an export file or a public API |
| `savedmap/sources/pinterest.py` | is supported by an existing library (gallery-dl here) |
| `savedmap/sources/instagram.py` | needs a logged-in browser |

## 1. Pick the least risky way in

Take the first of these that works:
1. An official API with the user's own token. Karakeep, for example, has a REST API with keys.
2. An official data export file.
3. A maintained library: gallery-dl, yt-dlp, or the platform's SDK.
4. A logged-in browser calling the platform's own web endpoints, with pacing.

Explain the choice and its account risk to the user before writing code. Never bypass logins, captchas or rate limits.

## 2. Implement the contract

Write `savedmap/sources/<name>.py` with a `Source` subclass (see `sources/base.py`):
- `name`, `needs_login` (True means the ban guard applies), and `login(cfg)` if it needs one.
- `fetch(cfg, known, full, max_pages, cursor=None) -> Batch`:
  - Return pydantic `Item`s, newest saved first.
  - Stop early when a page is all `known` (incremental), and never make more than `max_pages` requests.
  - Set `complete=True` only when the list is the whole saved set; that is what marks unsaved items as removed.
  - Set `cursor` when stopping at `max_pages` so the next run can continue.
- Raise `Blocked` when the platform pushes back (401/429, challenge) and `NeedsLogin` when the session is missing.
- In each `Item`:
  - `native_id`: a stable id; it ends up in file paths.
  - `kind`: post, pin or book. Add a new kind only if the viewer needs it.
  - `media`: `Media(kind="image"|"video"|"cover", url=…)`. The shared downloader fetches it without cookies.
  - `details`: the extras the viewer shows.

Then:
- Register the source in `savedmap/sources/__init__.py`.
- Add its settings model to `savedmap/config.py` (`Sources`), and a commented block to `TEMPLATE`.
- Add its display name, icon (a Lucide name) and colour to `PLATFORMS` in `savedmap/static/app.js`.

## 3. Test without network

Record one or two real responses, trim them to the fields you use, and put them in `tests/fixtures/`. Add a test in `tests/test_sources.py` that parses them into the expected `Item`s, and run `uv run pytest -q`.

## 4. Try it for real, gently

Only with the user's OK:
1. `uv run savedmap update --source <name> --dry-run`, which makes one request.
2. A real update.
3. Check the app.

## 5. Write the connect skill

Copy `.claude/skills/connect-goodreads/SKILL.md` to `.claude/skills/connect-<name>/SKILL.md` and adapt it: risk, login or export, config, dry run, first sync, checks, troubleshooting. Add the platform to `README.md` and `docs/DESIGN.md`.
