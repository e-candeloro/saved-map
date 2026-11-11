# SavedMap: agent guide

Local library of a person's saves from Instagram, Pinterest, YouTube and Goodreads: download, analyse (transcripts, OCR, embeddings, a small LLM), then browse by collection, topic, map and search in a local web app. Read `docs/DESIGN.md` before changing behaviour; `README.md` is the user-facing summary.

## Map

| Path | What |
| --- | --- |
| `savedmap/sources/` | one connector per platform, all on the contract in `base.py` (`Item`, `Batch`, `Blocked`, `NeedsLogin`) |
| `savedmap/update.py` | `savedmap update`: guard → fetch → store → download → process → refine → cluster → `data/hooks/after-update` if present |
| `savedmap/process.py` | thumbs, frames, speech, OCR, visual, text, topics (each stage only does what is missing) |
| `savedmap/refine.py`, `llm.py` | LLM title/summary/tags through one OpenAI-compatible client (Ollama by default), pydantic output |
| `savedmap/cluster.py` | UMAP + HDBSCAN maps and labels → `data/layout.json` |
| `savedmap/web.py`, `static/` | FastAPI app and the one-page UI (`app.js`, `index.html`, prebuilt `app.css` + `icons.js`) |
| `savedmap/config.py` | pydantic models for `data/config.toml`; the Settings menu writes it with tomlkit |
| `.claude/skills/` | `savedmap-setup`, `connect-<platform>`, `add-source` (ours); `unslop` (third party, CC BY 4.0) |
| `Dockerfile`, `compose.yaml` | CPU image of the web app; `SAVEDMAP_READ_ONLY=1` turns off Update and Settings (a copy synced by another machine) |
| `docs/demo-video/` | HyperFrames source and recorder for the README demo |
| `data/` | the user's library (gitignored, often a symlink). Never commit anything from it |

## Commands

```bash
uv sync                      # deps
uv run pytest -q             # tests: no network, temp data folder
uv run savedmap serve        # http://127.0.0.1:8770
uv run savedmap status       # items per platform, when the next sync is allowed
docker compose up -d         # read-only CPU copy of ./data on :8770
scripts/build_ui.sh          # after changing classes/icons in savedmap/static (rebuilds app.css + icons.js)
```

## Rules

- **Never contact a platform without the user's explicit OK** in this conversation: no `update` (dry run included), `connect` or recorder run against Instagram, Pinterest or YouTube on your own. Never raise `[guard]` limits or use `--force` unasked. Goodreads/YouTube Takeout imports read local files, but YouTube still does anonymous lookups.
- **Private data stays private:** `data/`, `browser-profile/`, cookies and `config.toml` never go into git, logs, docs or test fixtures. Fixtures are trimmed or synthetic.
- **Keep it simple:** one contract for sources, shared storage/download/guard, no new framework or build step for users. New platform → follow the `add-source` skill.
- **UI:** Tailwind classes + tokens in `static/app.src.css`; run `scripts/build_ui.sh` and commit `app.css`/`icons.js` with the change. Keep Lighthouse (mobile ≥ 85, accessibility 100) and the phone layout working.
- **Verify:** `uv run pytest -q`; for UI changes, load the app in a headless browser and check the console; for pipeline changes, run the affected stage on the real data only when the user asked.
- Commits: local only unless asked; end messages with the co-author line the session gives.
