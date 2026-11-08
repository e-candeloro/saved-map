"""Each connector turns recorded platform data into Items, without network."""
import json
from pathlib import Path

from savedmap.sources import instagram

FIX = Path(__file__).parent / "fixtures"


def test_instagram_node():
    node = json.loads((FIX / "instagram_node.json").read_text())
    it = instagram.to_item(node, {"111": "Books"})
    assert it.native_id == "DAbc_123" and it.kind == "post" and it.url == "https://www.instagram.com/p/DAbc_123/"
    assert it.author == "someone" and it.text == "A caption" and it.details["likes"] == 42
    assert it.collections == [("111", "Books"), ("222", "")]
    assert [(m.kind, m.url) for m in it.media] == [("video", "https://cdn/v_hi.mp4"), ("cover", "https://cdn/i_big.jpg")]


def test_goodreads_csv(monkeypatch):
    from savedmap.config import Config, Goodreads, Sources
    from savedmap.sources import goodreads

    monkeypatch.setattr(goodreads, "open_library", lambda client, row: {"cover_i": 7, "subject": ["fantasy", "friendship"]})
    cfg = Config(sources=Sources(goodreads=Goodreads(export_csv=str(FIX / "goodreads_library_export*.csv"))))
    batch = goodreads.Goodreads().fetch(cfg, known={"234225"}, full=False, max_pages=1)
    assert batch.complete and [b.native_id for b in batch.items] == ["234225", "157993"]  # newest added first
    dune, prince = batch.items
    assert dune.text is None and dune.media == []  # known book: stored text and cover are kept
    assert prince.title == "The Little Prince" and prince.author == "Antoine de Saint-Exupéry"
    assert prince.text == "Simple and sad.\nLoved it.\nSubjects: fantasy, friendship"
    assert prince.media[0].url == "https://covers.openlibrary.org/b/id/7-L.jpg"
    assert prince.details["rating"] == 5 and prince.details["isbn"] == "9780156012195"
    assert [c[0] for c in prince.collections] == ["read", "favorites"]
    assert goodreads.clean_isbn('="0156012197"') == "0156012197"


def test_pinterest_pins():
    from savedmap.sources import pinterest
    story, plain, video = [pinterest.to_item(p) for p in json.loads((FIX / "pinterest_pins.json").read_text())]
    assert story.kind == "pin" and story.title == "Cozy Living Room Ideas" and story.url.startswith("https://www.pinterest.com/pin/")
    assert story.native_id == "0123456789abcdef0123456789abcdef"  # image signature, not the session-dependent pin id
    assert story.author == "example_creator" and story.details["link"] == "https://example.com/living-room"
    assert plain.title is None and [m.kind for m in plain.media] == ["image"] and plain.media[0].url.startswith("https://i.pinimg.com/originals/")
    assert [(m.kind, m.url) for m in video.media] == [("video", "https://v.pinimg.com/x_720.mp4"), ("cover", plain.media[0].url)]


def test_youtube_takeout(tmp_path):
    from savedmap.sources import youtube
    pl = tmp_path / "YouTube e YouTube Music" / "playlist"
    pl.mkdir(parents=True)
    (pl / "playlist.csv").write_text("ID playlist,Titolo\nPLx,Cooking\n")
    (pl / "Cooking 🍖 - video.csv").write_text("ID video,Timestamp\ndQw4w9WgXcQ,2024-09-06T21:40:33+00:00\n -N75CZJ3qJQ,2024-09-01T00:00:00+00:00\n")
    (pl / "Watch later - video.csv").write_text("ID video,Timestamp\nZ-husjZkxHw,2026-01-01T00:00:00+00:00\n")
    ml = tmp_path / "YouTube e YouTube Music" / "music (library and uploads)"
    ml.mkdir()
    (ml / "music library songs.csv").write_text("ID video,Song Title,Album Title,Artist Name 1,Artist Name 2\nYZEzhBBuf7E,Suite 2,OST,Hiroyuki Sawano,\n")
    entries, songs = youtube.read_export(tmp_path, ["Watch later"], True)
    assert entries == [("dQw4w9WgXcQ", "Cooking 🍖", "2024-09-06T21:40:33+00:00"),
                       ("-N75CZJ3qJQ", "Cooking 🍖", "2024-09-01T00:00:00+00:00")] and list(songs) == ["YZEzhBBuf7E"]
    meta = {"title": "Full title", "channel": "Chan", "description": " About it \n", "upload_date": "20091025",
            "duration": 212, "chapters": [{"title": "Intro"}]}
    new = youtube.to_item("dQw4w9WgXcQ", meta, [("Cooking", "Cooking")], None)
    assert new.kind == "video" and new.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert (new.title, new.author, new.text) == ("Full title", "Chan", "About it") and new.details["chapters"] == ["Intro"]
    assert new.media[0].url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert youtube.to_item("dQw4w9WgXcQ", None, [], None).text is None  # known: stored description kept
    assert youtube.to_item("dQw4w9WgXcQ", {}, [], None).details["unavailable"]
    song = youtube.to_item("YZEzhBBuf7E", {}, [("music-library", "Music library")], songs["YZEzhBBuf7E"])
    assert (song.title, song.author, song.text) == ("Suite 2", "Hiroyuki Sawano", "Song by Hiroyuki Sawano, album OST")
