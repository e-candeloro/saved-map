---
name: connect-karakeep
description: Connect a user's self-hosted Karakeep (bookmarks, notes, PDFs and images, with their lists and tags) to SavedMap through Karakeep's REST API and an API key. No platform account involved, no ban risk. Use when the user wants to add or refresh Karakeep in SavedMap.
---

# Connect Karakeep

[Karakeep](https://karakeep.app) is a self-hosted bookmark manager. SavedMap reads it through the official REST API with an API key the user creates. Only the user's own server is contacted, so the ban guard doesn't apply. Pictures are the ones Karakeep already stored (the page's banner, else its screenshot), so the bookmarked sites aren't contacted either. Tested with Karakeep 0.33.

## Steps

1. **Key:** the user opens Karakeep → **Settings → API Keys**, creates a key named `savedmap`, and keeps it out of the chat. The key can also edit and delete in Karakeep (there are no read-only keys); SavedMap only reads.
2. **Environment:** the key goes in the environment variable `KARAKEEP_API_KEY`. A user can store it from their own terminal, without it showing on screen:
   ```bash
   (umask 077; mkdir -p ~/.config/savedmap; read -rsp 'Karakeep key: ' K; echo; printf 'export KARAKEEP_API_KEY=%q\n' "$K" > ~/.config/savedmap/env)
   echo '[ -f ~/.config/savedmap/env ] && . ~/.config/savedmap/env' >> ~/.bashrc
   ```
   Start `savedmap serve` from a new terminal, so the Update button sees the key too.
3. **Config:** in `data/config.toml`, set `[sources.karakeep] enabled = true` and `url` to the server's address, e.g. `https://karakeep.example.com`.
4. **Check:** `uv run savedmap update --source karakeep --dry-run` reads one page of bookmarks and stores nothing.
5. **Import:** `uv run savedmap update --source karakeep`. It reads every bookmark (100 per request) and every list, gets a signed link for each new bookmark's picture, then downloads and processes like any other source.
6. **Check:** `uv run savedmap status`; in the app, filter *Karakeep* or a list under **Lists**.

## Updating

Every `savedmap update` reads the whole list again. That's a few requests for hundreds of bookmarks. New bookmarks are added; deleted ones are marked *no longer saved*; titles, notes, tags and lists are refreshed.

## Notes

- Kinds: links show their stored picture and open the original page from the viewer's link; text notes and bookmarks without a picture get a plain title card. PDFs show their first-page screenshot and up to 4,000 characters of their text.
- Tags go into the searchable text and the description; Karakeep's own AI summary is used if it has one.
- **Troubleshooting:**
  - "rejected the key": the variable is missing in that terminal or the key was revoked.
  - "can't reach Karakeep": the server is off, or `url` is wrong.
  - In both cases the other sources still update.
