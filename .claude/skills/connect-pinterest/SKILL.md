---
name: connect-pinterest
description: Connect a user's Pinterest boards and pins to SavedMap, public boards without login or secret boards with a one-time login. Uses gallery-dl's Pinterest client with pacing. Use when the user wants to add, reconnect or troubleshoot Pinterest in SavedMap.
---

# Connect Pinterest

SavedMap reads Pinterest boards through [gallery-dl](https://github.com/mikf/gallery-dl)'s Pinterest web-API client:
- requests are 2–6 s apart;
- boards come sorted by the last pin added, so an update stops at the first board with nothing new;
- pins are keyed by their image signature, which stays the same with or without login;
- files are downloaded without cookies.

## Pick the mode with the user

- **Public boards only** (`login = false`): no login, so no risk to the account. Secret boards are skipped.
- **Include secret boards** (`login = true`): the user logs in once in SavedMap's dedicated Chrome window. Its cookies are exported to `data/pinterest-cookies.txt` (owner-only permissions, never committed) for each sync. This is automated use of their account, so say so and get their OK.

## Steps

1. **Config:** in `data/config.toml`, set `[sources.pinterest] enabled = true` and `user = "<profile name>"`, as in `pinterest.com/<name>/`; regional domains like `it.pinterest.com` don't matter. Set `login` to match the mode chosen above.
2. **Log in** (secret boards only): run `uv run savedmap connect pinterest` and have the user log in in the Chrome window.
3. **Dry run:** `uv run savedmap update --source pinterest --dry-run` makes one request.
4. **First sync:** `uv run savedmap update --source pinterest`. It takes about 1 request per 25 pins plus 1 per board, up to 200 requests.
5. **Check:** `uv run savedmap status`; in the app, the sidebar shows Pinterest boards under *Boards*.

## Troubleshooting

- **`Pinterest user ... not found`:** check the profile name in `config.toml`.
- **`stopped: Pinterest API request failed`:** the 72 h pause is on. With login, ask the user to check Pinterest in their normal browser.
- **Secret boards missing:** confirm `login = true` and run step 2 again. The cookies file must contain `_auth 1`.
- **gallery-dl broke after a Pinterest change:** `uv lock --upgrade-package gallery-dl && uv sync`, then run the tests.
- **Fallback with zero automation:** Pinterest's own data export (Settings → Privacy and data → Request your data) still works, but SavedMap doesn't import it yet.
