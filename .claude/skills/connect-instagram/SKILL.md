---
name: connect-instagram
description: Connect a user's Instagram saved posts to SavedMap. Covers ban risk, one-time login in the dedicated Chrome window, a one-request dry run, the first sync and checks. Use when the user wants to add, reconnect or troubleshoot Instagram in SavedMap.
---

# Connect Instagram

SavedMap reads Instagram's saved feed from a real Chrome window using a dedicated profile (`browser-profile/`, gitignored). Each request returns ~21 posts with their collections and media links. Media is then downloaded from the CDN without cookies.

## Before anything: say the risk

This is automated use of the user's account, which Instagram's terms don't allow. SavedMap keeps it close to normal browsing with these limits:
- requests 3–8 s apart;
- syncs stop at the first page of posts already stored;
- at least 12 h between syncs;
- a 72 h pause if Instagram pushes back.

Get the user's OK before the first request. Never raise the `[guard]` limits on your own, and never run requests in a loop.

## Steps

1. **Config:** in `data/config.toml`, set `[sources.instagram] enabled = true` and `user = "<username>"`.
2. **Log in once:** run `uv run savedmap connect instagram`. A Chrome window opens; the user logs in there, with 2FA if needed. The window closes by itself once logged in.
3. **Dry run:** `uv run savedmap update --source instagram --dry-run` makes one request and stores nothing. It should print `OK: first page has 21 items`.
4. **First sync:** `uv run savedmap update --source instagram`.
   - It fetches up to 200 requests (~4000 posts), then downloads the media.
   - A bigger library continues in the next update after 12 h, from where it stopped.
   - After downloading it processes everything: transcripts, OCR, embeddings, LLM step, map. With a 4 GB GPU, ~2800 posts take about 6–7 h, so suggest running it overnight.
5. **Check:**
   - `uv run savedmap status` shows the item count;
   - `uv run savedmap serve`, then http://127.0.0.1:8770, shows the posts with the Instagram collections in the sidebar.

## Troubleshooting

- **`Not logged in` / `asked to log in again`:** run step 2 again.
- **`stopped: Instagram answered HTTP 4xx`:** the 72 h pause is on. Ask the user to open Instagram in their normal browser and confirm any security prompt. Don't retry early.
- **Downloads failed (expired links):** links are signed and expire after a while. `uv run savedmap update --source instagram --full` refreshes them, at most once every 30 days.
- **New collections show without a name:** names come from the saved page and are filled in on the next sync.
