---
name: connect-youtube
description: Connect a user's YouTube playlists and YouTube Music library to SavedMap from a Google Takeout export. No login; titles and descriptions are looked up anonymously; only thumbnails are downloaded and videos play in an embedded player. Use when the user wants to add or refresh YouTube in SavedMap.
---

# Connect YouTube

SavedMap reads YouTube from a Google Takeout export, so it never logs into the account:
- titles, channels and descriptions are looked up with yt-dlp without cookies, one video every 1.5–3.5 s, only for new videos, in batches;
- only thumbnails are downloaded;
- the viewer embeds the YouTube player.

Liked videos are **not** in Takeout. Google treats them as a system playlist, so tell the user they are out of scope.

## Steps

1. **Export:** the user exports at https://takeout.google.com:
   - click **Deselect all**, then tick **YouTube and YouTube Music**;
   - under *All YouTube data included*, keep **playlists** and **music library**;
   - make sure it's the right Google account (the avatar at the top right), because a second account gives an almost empty export;
   - download the zip and unpack it, by default into `~/Downloads/Takeout`.
2. **Config:** in `data/config.toml`, under `[sources.youtube]`:
   - set `enabled = true`;
   - set `takeout` to the unpacked folder; any parent of the YouTube folder works;
   - keep `skip_playlists = ["Watch later"]` unless the user wants it (often thousands of videos);
   - set `music_library` to match whether they want songs.
3. **Import:** run `uv run savedmap update --source youtube`.
   - It prints how many videos need a lookup and roughly how long that takes (~4.5 s each).
   - Lookups are cached in `data/imports/youtube/metadata.json`, so an interrupted run continues where it stopped.
4. **Check:** `uv run savedmap status`. In the app, the *YouTube* platform and its *Playlists* appear in the sidebar, and opening a video plays it.

## Updating

Export again (Takeout can schedule an export every 2 months) and press Update. Only new videos are looked up. Videos removed from a playlist are marked *no longer saved*, and deleted or private ones *unavailable*.

## Troubleshooting

- **`No YouTube playlist CSVs under …`:** `takeout` points to the wrong folder, or the export is from another account.
- **`YouTube rate-limited the lookups`:** wait a few hours and run update again; the cache keeps what was already fetched.
