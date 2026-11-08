---
name: connect-goodreads
description: Connect a user's Goodreads library (books, shelves, ratings, reviews) to SavedMap from the official CSV export, with covers and subjects from Open Library. No login, no account risk. Use when the user wants to add or refresh Goodreads in SavedMap.
---

# Connect Goodreads

Goodreads retired its API in 2020. By late 2026 its public shelf RSS feeds return 404 and shelf pages need a login. So SavedMap reads the official library export, a CSV that holds every book, shelf, rating and review. SavedMap never contacts Goodreads, so there is nothing to ban.

## Steps

1. **Export:** the user exports their library: goodreads.com (desktop site) → **My Books** → **Tools** → **Import and export** → **Export Library**, then downloads the CSV. The file is called `goodreads_library_export.csv`.
2. **Config:** in `data/config.toml`, set `[sources.goodreads] enabled = true`. `export_csv` defaults to `~/Downloads/goodreads_library_export*.csv`; change it if the file is somewhere else. The newest matching file is used.
3. **Import:** run `uv run savedmap update --source goodreads`.
   - New books get a cover and subjects from Open Library's public API, about 1 request/s, so 250 books take about 5 min.
   - A dated copy of the export is kept in `data/imports/goodreads/`.
   - Then books are processed and described like any other item.
4. **Check:** `uv run savedmap status`. In the app, filter *Goodreads* or the *books & reading* topic. That topic also shows reels and pins about books.

## Updating

Export again and run `uv run savedmap update`. Only new books are looked up. The export holds the whole library, so books removed on Goodreads are marked *no longer saved*.

## Notes

- Books without an ISBN (many Kindle editions) are matched by title and author. A few may get no cover or the wrong one, and the grid then shows the title.
- Ratings, review, shelves and read date appear in the book viewer.
