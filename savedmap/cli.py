import argparse


def main():
    from .sources import SOURCES
    ap = argparse.ArgumentParser(prog="savedmap", description="Local library of what you saved on Instagram, Pinterest and Goodreads")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the data folder and config.toml")
    sub.add_parser("migrate", help="one time: move a v0.1 (Instagram-only) data folder to the multi-platform layout")
    c = sub.add_parser("connect", help="log in to a platform once in the dedicated Chrome window")
    c.add_argument("source", choices=list(SOURCES))
    u = sub.add_parser("update", help="fetch only new saves from enabled platforms, then download, process, refine, cluster")
    u.add_argument("--source", nargs="+", choices=list(SOURCES), help="only these platforms")
    u.add_argument("--full", action="store_true", help="re-read whole saved lists: notices unsaved items, refreshes collections (rate-limited)")
    u.add_argument("--dry-run", action="store_true", help="one request per platform to check the connection; stores nothing")
    u.add_argument("--no-process", action="store_true", help="only fetch and download")
    u.add_argument("--force", action="store_true", help="skip the waiting intervals (never the pause after a platform pushed back)")
    sub.add_parser("status", help="per platform: items, last sync, when the next sync is allowed")
    sub.add_parser("download", help="retry pending downloads (no platform requests)")
    pr = sub.add_parser("process", help="thumbnails, transcripts, OCR, embeddings")
    pr.add_argument("--only", nargs="+", metavar="STAGE", help="thumbs frames speech ocr visual text topics")
    pr.add_argument("--skip", nargs="+", metavar="STAGE")
    r = sub.add_parser("refine", help="LLM writes an English title, summary and tags per item")
    r.add_argument("--limit", type=int, help="only this many items (for testing)")
    sub.add_parser("cluster", help="build the 2D maps and clusters")
    w = sub.add_parser("serve", help="run the web app")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8770)
    a = ap.parse_args()

    if a.cmd == "init":
        from . import config
        config.init()
    elif a.cmd == "migrate":
        from .migrate import run
        run()
    elif a.cmd == "connect":
        from . import config
        SOURCES[a.source].login(config.load())
    elif a.cmd == "update":
        from .update import run
        run(a.source, a.full, a.dry_run, not a.no_process, a.force)
    elif a.cmd == "status":
        from . import config, db
        from .update import status, when
        for s in status(db.connect(), config.load()):
            last = when(s["last"]) if s["last"] else "never"
            print(f"{s['source']:10} {s['count']:5} items  last sync {last}  " + ("sync allowed" if s["allowed"] else s["reason"]))
    elif a.cmd == "download":
        from . import db
        from .download import download_all
        download_all(db.connect())
    elif a.cmd == "process":
        from .process import run
        run(a.only, a.skip)
    elif a.cmd == "refine":
        from .refine import run
        run(a.limit)
    elif a.cmd == "cluster":
        from .cluster import run
        run()
    elif a.cmd == "serve":
        from .web import serve
        serve(a.host, a.port)


if __name__ == "__main__":
    main()
