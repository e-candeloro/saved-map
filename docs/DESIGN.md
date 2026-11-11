# SavedMap design

SavedMap is a local library of everything you saved on social platforms. It covers Instagram saved posts, Pinterest pins, YouTube playlists and Goodreads books. You can browse it by collection, on a map that groups similar items, and with search by what an item shows, says or is about. Everything is downloaded and runs on your own machine. The goal is to give people their saved content back, not to make money.

Status: v0.2 prototype. A read-only Docker copy serves the library to other devices; syncing and processing stay on your computer.

## Jobs to be done

| Job (priority order) | Use case | Feature |
| --- | --- | --- |
| Find a specific thing | "that pasta reel from months ago" | search over speech, on-screen text, captions and summaries; filters for platform, topic and collection |
| Act on a topic | "date ideas for Saturday", "books to read next" | topic filter across platforms (e.g. *books* = Goodreads books + reels and pins about books), plus each platform's own collections, boards and shelves |
| Rediscover | wander, resurface forgotten saves | map clustered by look or topic; *Related* items in the viewer (nearest by look + topic, two slots kept for other platforms); *Surprise me* |
| Stay current | new saves show up without effort | **Update** button or `savedmap update`: fetches only new items, then processes them |

**Out of scope for v0.2:**
- curation (notes, done marks, own tags)
- posting to platforms
- scheduled syncs
- multi-user, auth or hosting
- mobile app
- syncing or processing inside Docker (the container is a read-only viewer)
- more than three sources
- cloud embeddings or OCR

## User journey

1. Clone the repo and open Claude Code in it.
2. Run `/savedmap-setup`. It checks the GPU, ffmpeg and uv, installs Ollama with a small model, and writes `data/config.toml`.
3. Connect each platform with `/connect-instagram`, `/connect-pinterest` or `/connect-goodreads`. Each skill:
   - explains the risk;
   - opens the login, or explains the export;
   - runs a one-request dry run;
   - runs the first sync;
   - checks the counts.
4. Let the first processing run: overnight on a GPU, or faster with a cloud API key (see [Compute and cost](#compute-and-cost)).
5. Open `savedmap serve` → http://127.0.0.1:8770.
6. Later, press **Update** now and then. It shows each source's last sync and when the next one is allowed.

## Architecture

The stack is Python, SQLite, FastAPI and a single-page vanilla JS frontend, with no build step. The design rule: reuse existing tools, and add one small abstraction only where platforms differ.

```
sources/<platform>.py ──Batch──▶ update.py ──▶ download.py ──▶ process.py ──▶ refine.py ──▶ cluster.py ──▶ web.py
  only new items               guard, store,    shared HTTP      Whisper, OCR,    LLM: title,     UMAP +
                               mark removed     downloader       SigLIP2, e5      summary, tags,  HDBSCAN
                                                                                  topics
```

### Connector contract

`savedmap/sources/base.py` defines the only abstraction:
- **`Source`:** has `name`, `needs_login`, `login(cfg)` and `fetch(cfg, known_ids, full, max_pages) -> Batch`.
- **`Batch`:** a list of `Item`s, newest saved first, plus `complete`. `complete` is true when the list is the whole saved set, so missing items can be marked *removed*.
- **`Item`:** a platform-neutral record with `native_id`, `kind` (post / pin / book), `url`, `author`, `title`, `text`, `created_at`, `collections` as `(id, name)` pairs, `media` and `details`. A `Media` entry has either a `url` for the shared downloader or a `path` if the source downloaded the file itself.
- **`Blocked`:** a source raises it when the platform pushes back (401, 429, login challenge).

`sources/__init__.py` maps names to sources. Adding a platform takes one module, one dict entry, one fixture test and one `connect-<platform>` skill. The `add-source` skill walks through it.

### Platforms

| Platform | How it fetches | Media | Account risk |
| --- | --- | --- | --- |
| Instagram | Real Chrome with a dedicated profile, logged in once, calls the saved-feed JSON the web app uses. ~21 posts per request, 3–8 s apart with longer breaks. Stops at the first page of known posts. | signed CDN links → shared downloader, no cookies | low, with the guard |
| Pinterest | [gallery-dl](https://github.com/mikf/gallery-dl)'s Pinterest web-API client, used as a library, with requests 2–6 s apart. Boards come sorted by last pin added, so an update stops at the first board with nothing new. Pins are keyed by image signature, which stays stable with or without login. Login cookies are exported from the same Chrome profile only when secret boards are wanted. | image or mp4 links → shared downloader | low; none without login |
| Goodreads | The official library CSV export: the API was retired in 2020, and by Nov 2026 the public shelf RSS feeds return 404 and shelf pages need a login. The newest export in `~/Downloads` is read on each update; it is the whole library, so removed books are noticed too. | covers and subjects from Open Library's public API, once per new book | none, no login |

### Ban guard

Written once in `update.py`; it applies to every source that needs a login:
- at least 12 h between syncs of a source;
- at most 40 pages per incremental sync, 200 for the first sync or a full one;
- `--full`, which is needed to notice unsaved items, at most once every 30 days;
- one source at a time, never in parallel;
- a `Blocked` error stops the run and starts a 72 h cooldown, and the UI and CLI say why and what to do.

There is no background schedule.

### Data

SQLite in WAL mode, one file in the data folder next to `media/`, `thumbs/`, `frames/` and `layout.json`. The data folder is `./data`, which can be a symlink to another disk. Tables:

| Table | Holds |
| --- | --- |
| `items` | `id` = `<source>:<native_id>`; `source`, `kind`, `url`, `author`, `title`, `text`, `details` JSON, `status` (active / removed), `saved_pos` |
| `collections` + `memberships` | Instagram collections, Pinterest boards, Goodreads shelves |
| `media` | files per item: kind, path, source URL |
| `analysis` | transcript, OCR, embeddings, LLM title, summary, tags; `topics`: the 1–3 entries of the editable [`topics.txt`](../savedmap/topics.txt) closest to the item by e5 similarity (more reliable than asking the 1.7B LLM) |

Unsaved items are kept and marked *removed*; the UI hides them by default.

### Processing and models

Each step only handles new items, so an update costs minutes.
- **Always local:**
  - Whisper transcripts with `faster-whisper` (cuda or cpu, chosen automatically);
  - EasyOCR;
  - SigLIP2 image embeddings;
  - multilingual-e5 text embeddings.

  Search and the map depend on one fixed embedding space, so embeddings and OCR stay local.
- **Swappable through one OpenAI-compatible client** (`savedmap/llm.py`):
  - the LLM step: Ollama `qwen3:1.7b` by default, or any OpenAI-compatible endpoint;
  - transcription: Groq or OpenAI.

  It is set in `config.toml` with `base_url`, `model` and `api_key_env`. Keys are only read from environment variables.

### UI

The UI is one page. Tailwind v4 CSS and a Lucide icon subset are prebuilt by `scripts/build_ui.sh` and committed, so users have no build step and the page ships about 10 KB of CSS and icons instead of a 770 KB runtime. Custom CSS is used only for the canvas map. The list API is slim (gzip, about 430 KB for 4,400 items); long texts load per item and the map layout after the first paint. Thumbnails are 256 px WebP. Lighthouse: Performance 99 desktop / 86 mobile, Accessibility 100, Best practices 100.

- **Top bar:**
  - search;
  - Grid / Map;
  - map mode;
  - Update, with status;
  - Surprise me.
- **Sidebar:**
  - platform;
  - topics;
  - collections grouped by platform;
  - clusters;
  - a toggle to show removed items.
- **Viewer:** one per kind:
  - post: media, transcript, on-screen text;
  - pin: image or video, board;
  - book: cover, author, rating, review, shelves.

Usability follows Nielsen's heuristics:

| Heuristic | In SavedMap |
| --- | --- |
| Status visibility | update progress and next allowed sync, result counts, thumbnail loading |
| Real-world match | each platform's own words: collections, boards, shelves |
| User control | removable filter chips, *Clear all*, Esc closes the viewer, filters kept in the URL |
| Consistency | one chip style, one button style, one icon set |
| Error prevention | Update is disabled with the reason during a cooldown |
| Recognition rather than recall | all filters are visible choices |
| Flexibility | keys: `/` search, `←`/`→` next and previous item, `g`/`m` grid and map |
| Minimalist design | quiet chrome; colour only in content and cluster dots |
| Error recovery | plain messages that say what happened and the next step |
| Help | empty states name the command or skill to run |

The visual pass uses the [unslop](https://github.com/heydamir/unslop) skill, installed in `.claude/skills/`.

## Claude Code skills

The skills live in `.claude/skills/`. They guide and call the CLI; the Python code does the work, so a run gives the same result with or without Claude.

| Skill | Purpose |
| --- | --- |
| `savedmap-setup` | install, checks, config |
| `connect-instagram`, `connect-pinterest`, `connect-goodreads` | connect one platform: risk, login or link, dry run, first sync, verify |
| `add-source` | write a new connector against the contract |
| `unslop` | design pass on the UI (third party, CC BY 4.0) |

## Compute and cost

The reference library has 2853 items and ~29 h of audio. The LLM step uses ≈ 1.5k input + 0.2k output tokens per item.

| Step | Local GPU (GTX 1650 Ti, 4 GB) | Local CPU | Cloud (prices from third-party aggregators, Nov 2026; check before use) |
| --- | --- | --- | --- |
| Transcription, 29 h audio | ~4–5 h | ~1 s per audio second, ≈ 29 h | Groq whisper-large-v3-turbo ≈ $0.04/h → **≈ $1.2**; OpenAI gpt-4o-mini-transcribe $0.003/min → **≈ $5** |
| LLM step, 2853 items | ~75 min | several hours | GPT-5 nano ≈ $0.05 / $0.40 per 1M tokens → **≈ $0.5**; DeepSeek or Gemini Flash-Lite **≈ $1–2** |
| Weekly update, ~50 items | minutes | ~30 min | cents |

The full local GPU run uses about 0.7 kWh. The cloud options send audio and text off the machine, so the default stays local.

## Risks

| Risk | Mitigation |
| --- | --- |
| Platform internals change | gallery-dl is maintained upstream; the Instagram code is isolated in one module; Pinterest's data export is a manual fallback |
| Account flags | the guard; Pinterest without login; no schedule |
| Data loss in the schema migration | `savedmap migrate` makes a backup first and compares counts |
| Weak topic labels | edit `topics.txt` and the next `savedmap process` re-tags everything |

## YouTube (playlists and music library)

Decisions with the user (2026-11-08):
- **Source:** Google Takeout only, so no login.
- **Context:** title and description; no transcripts.
- **Scope:** the user's playlists and Favorites plus the YouTube Music library. *Watch later* is skipped (`skip_playlists`).

Google leaves *Liked videos* out of Takeout (checked on a real export), so likes aren't imported. A yt-dlp login path for them was built and then dropped.

| Step | Choice | Why |
| --- | --- | --- |
| Which videos | The unpacked Takeout folder: one CSV per playlist (video ID + time added), plus `music library songs.csv` (title, album, artists). Files are recognised by their columns, not their names, because Takeout localizes them (`playlist/Cooking - video.csv`, `ID video`). A dated copy is kept in `data/imports/youtube/`. | Official and complete, so removals are noticed. No account automation. |
| Title, channel, description | yt-dlp metadata only, without cookies (`player_skip: js`), one video per request, 1.5–3.5 s apart, only for new videos, at most one batch (`max_pages`) per run so a big import is stored and processed batch by batch, cached in `data/imports/youtube/metadata.json` | Takeout has only IDs. Requests are anonymous, so the account is never involved. A 429 stops the run and the cache keeps the progress. |
| Thumbnail | `i.ytimg.com/vi/<id>/hqdefault.jpg` through the shared downloader | Static image CDN |
| Viewer | `youtube-nocookie.com/embed/<id>` iframe; offline, the thumbnail links to YouTube | Plays without downloading |
| Processing | no Whisper or frames; OCR + SigLIP on the thumbnail; e5 + LLM on title + description | The pipeline already skips stages that have no input |

Updating means exporting again (Takeout can also schedule an export every 2 months) and pressing Update. Deleted or private videos are kept and marked *unavailable*.

## Later

Karakeep and other sources, a list view with sorting, curation if real use asks for it.
