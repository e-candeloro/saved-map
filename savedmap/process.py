"""Local analysis of downloaded items, one model at a time so it fits a 4 GB GPU.

Stages (each only touches items it hasn't done yet):
  thumbs  -> 320px JPEG per item for the grid and the map
  frames  -> a frame every 3 s of each video (cached, max 12 per video)
  speech  -> transcript of every video (faster-whisper, or an OpenAI-compatible API via config)
  ocr     -> on-screen text from images and video frames (EasyOCR, it+en; covers are skipped)
  visual  -> SigLIP2 embedding: mean over images and frames (or the cover)
  text    -> multilingual-e5 embedding of title + summary + tags + text + transcript + OCR
  topics  -> 1-3 broad topics from topics.txt (for the cross-platform topic filter)
"""
import gc
import os
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from . import config, db

_dev = config.load().models.device
DEVICE = ("cuda" if torch.cuda.is_available() else "cpu") if _dev == "auto" else _dev
SIGLIP = "google/siglip2-base-patch16-256"
E5 = "intfloat/multilingual-e5-base"
WHISPER = "large-v3-turbo"  # faster than medium on a GTX 1650 Ti and more accurate


def free():
    gc.collect()
    if DEVICE == "cuda":
        torch.cuda.empty_cache()


def media_of(con, item_id, kinds=("image", "video", "cover")):
    rows = con.execute(f"""SELECT kind, path FROM media WHERE item_id=? AND path IS NOT NULL
                           AND kind IN ({','.join('?' * len(kinds))}) ORDER BY idx""", (item_id, *kinds)).fetchall()
    return [(r["kind"], db.MEDIA_DIR / r["path"]) for r in rows]


def frames_of(con, item_id, step=1):
    """Images of the item plus cached video frames (every `step`-th; no cover: it duplicates a frame)."""
    out = [p for k, p in media_of(con, item_id, ("image",))]
    for i, (_, video) in enumerate(media_of(con, item_id, ("video",))):
        out += sorted((db.FRAMES_DIR / db.item_dir(item_id)).glob(f"v{i}_*.jpg"))[::step]
    return out


def ready(con, column=None):
    q = "SELECT i.id FROM items i LEFT JOIN analysis a ON a.item_id = i.id WHERE i.download_done=1"
    if column:
        q += f" AND a.{column} IS NULL"
    return [r["id"] for r in con.execute(q + " ORDER BY i.source, i.saved_pos").fetchall()]


def ensure_rows(con):
    con.execute("INSERT OR IGNORE INTO analysis(item_id) SELECT id FROM items WHERE download_done=1")


def title_card(item_id: str, title: str, author: str | None) -> str:
    """A plain cover for a book or bookmark without a picture, so it gets a thumbnail and a map spot."""
    from PIL import ImageDraw, ImageFont
    import textwrap
    im = Image.new("RGB", (400, 600), "#ece6da")
    d = ImageDraw.Draw(im)
    try:
        big, small = ImageFont.truetype("DejaVuSerif.ttf", 34), ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        big = small = ImageFont.load_default()
    y = 80
    for line in textwrap.wrap(title, 18)[:7]:
        d.text((40, y), line, fill="#2b2622", font=big)
        y += 46
    if author:
        d.text((40, y + 30), author, fill="#6b6257", font=small)
    rel = f"{db.item_dir(item_id)}/cover.jpg"
    (db.MEDIA_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
    im.save(db.MEDIA_DIR / rel, quality=90)
    return rel


def stage_thumbs(con):
    for r in con.execute("""SELECT i.id, i.title, i.author FROM items i WHERE i.kind IN ('book', 'bookmark') AND i.download_done=1
                            AND NOT EXISTS (SELECT 1 FROM media m WHERE m.item_id=i.id)""").fetchall():
        con.execute("INSERT INTO media (item_id, idx, kind, path) VALUES (?,0,'cover',?)",
                    (r["id"], title_card(r["id"], r["title"] or "Untitled", r["author"])))
    con.commit()
    for item_id in ready(con):
        out = db.thumb_path(item_id)
        if out.exists():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        media = media_of(con, item_id, ("cover",)) or media_of(con, item_id, ("image",))
        src = media[0][1] if media else None
        frame = out.with_suffix(".frame.jpg")
        if src is None and (vids := media_of(con, item_id, ("video",))):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", str(vids[0][1]), "-frames:v", "1", str(frame)])
            src = frame if frame.exists() else None
        if src:
            try:
                im = Image.open(src).convert("RGB")
            except OSError as e:
                print(f"\n  ! thumb {item_id}: {e}")
                continue
            im.thumbnail((256, 256))
            im.save(out, "WEBP", quality=80, method=4)
        frame.unlink(missing_ok=True)


def stage_frames(con):
    for item_id in ready(con):
        for i, (_, video) in enumerate(media_of(con, item_id, ("video",))):
            folder = db.FRAMES_DIR / db.item_dir(item_id)
            if list(folder.glob(f"v{i}_*.jpg")):
                continue
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", "fps=1/3,scale=640:-2",
                            "-frames:v", "12", "-q:v", "3", str(folder / f"v{i}_%02d.jpg")])


def load_audio(path) -> np.ndarray:
    """16 kHz mono float32 via ffmpeg (empty when the video has no audio)."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768


def mp3_of(path) -> bytes:
    """Small mono MP3 for cloud transcription (an hour is ~15 MB)."""
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
                           "-f", "mp3", "-"], capture_output=True).stdout


def stage_speech(con):
    todo = ready(con, "transcript")
    if not todo:
        return
    tc = config.load().models.transcribe
    if tc.backend == "api":
        from . import llm
        cl = llm.client(tc)

        def transcribe(video):
            if load_audio(video).size < 16000:
                return "", None
            return llm.transcribe(cl, tc.model, mp3_of(video))
    else:
        from faster_whisper import WhisperModel
        model = WhisperModel(WHISPER, device=DEVICE, compute_type="int8_float16" if DEVICE == "cuda" else "int8")

        def transcribe(video):
            audio = load_audio(video)
            if audio.size < 16000:  # no audio track, or under a second
                return "", None
            segments, info = model.transcribe(audio, vad_filter=True, beam_size=1)  # greedy: ~10% faster, same text in tests
            return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip(), info.language

    for n, item_id in enumerate(todo, 1):
        texts, lang = [], None
        try:
            for _, video in media_of(con, item_id, ("video",)):
                text, language = transcribe(video)
                if text:
                    texts.append(text)
                    lang = lang or language
        except Exception as e:  # one bad file must not stop an unattended run
            print(f"\n  ! speech {item_id}: {e}")
            free()
        con.execute("UPDATE analysis SET transcript=?, language=? WHERE item_id=?", ("\n".join(texts), lang, item_id))
        con.commit()
        print(f"  speech {n}/{len(todo)}", end="\r")
    free()


def stage_ocr(con):
    todo = ready(con, "ocr")
    if not todo:
        return
    jobs = [(item_id, frames_of(con, item_id, step=2)) for item_id in todo]  # every 6 s of video is enough
    for item_id, imgs in jobs:
        if not imgs:  # books (cover only), text-only items
            con.execute("UPDATE analysis SET ocr='' WHERE item_id=?", (item_id,))
    con.commit()
    jobs = [(i, imgs) for i, imgs in jobs if imgs]
    if not jobs:
        return
    import easyocr
    reader = easyocr.Reader(["it", "en"], gpu=DEVICE == "cuda", verbose=False)
    for n, (item_id, imgs) in enumerate(jobs, 1):
        lines, seen = [], set()
        for img in imgs:
            try:
                im = Image.open(img).convert("RGB")  # first frame of GIFs, any format
                im.thumbnail((1600, 1600))
                found = reader.readtext(np.asarray(im), canvas_size=1280)  # default 2560 runs out of a 4 GB GPU
            except Exception as e:
                print(f"\n  ! ocr {img}: {e}")
                free()
                continue
            for _, text, conf in found:
                key = "".join(ch for ch in text.lower() if ch.isalnum())
                if conf >= 0.4 and len(key) >= 3 and key not in seen:
                    seen.add(key)
                    lines.append(text)
        con.execute("UPDATE analysis SET ocr=? WHERE item_id=?", ("\n".join(lines), item_id))
        con.commit()
        print(f"  ocr {n}/{len(jobs)}", end="\r")
    del reader
    free()


class Siglip:
    """SigLIP2 image/text encoder in a shared space (multilingual text side)."""

    def __init__(self, device=DEVICE):
        from transformers import AutoModel, AutoProcessor
        self.device = device
        self.model = AutoModel.from_pretrained(SIGLIP, dtype=torch.float16 if device == "cuda" else torch.float32).to(device).eval()
        self.proc = AutoProcessor.from_pretrained(SIGLIP)

    @staticmethod
    def _norm(out):
        t = out if isinstance(out, torch.Tensor) else out.pooler_output
        return torch.nn.functional.normalize(t.float(), dim=-1).cpu().numpy()

    @torch.no_grad()
    def images(self, paths):
        ims = [Image.open(p).convert("RGB") for p in paths]
        x = self.proc(images=ims, return_tensors="pt").to(self.device)
        return self._norm(self.model.get_image_features(pixel_values=x["pixel_values"].to(self.model.dtype)))

    @torch.no_grad()
    def text(self, q):
        x = self.proc(text=[q.lower()], padding="max_length", max_length=64, truncation=True, return_tensors="pt").to(self.device)
        return self._norm(self.model.get_text_features(**x))[0]


def stage_visual(con):
    todo = ready(con, "visual_emb")
    if not todo:
        return
    enc = Siglip()
    for n, item_id in enumerate(todo, 1):
        paths = frames_of(con, item_id)[:16] or [p for _, p in media_of(con, item_id, ("cover",))]
        if not paths:
            continue
        try:
            v = enc.images(paths).mean(0)
        except Exception as e:
            print(f"\n  ! visual {item_id}: {e}")
            free()
            continue
        con.execute("UPDATE analysis SET visual_emb=? WHERE item_id=?", (db.to_blob(v / np.linalg.norm(v)), item_id))
        con.commit()
        print(f"  visual {n}/{len(todo)}", end="\r")
    del enc
    free()


TEXT_QUERY = """SELECT i.id, i.title AS item_title, i.author, i.text, a.transcript, a.ocr, a.title, a.summary, a.tags, a.topics,
                (SELECT group_concat(c.name, ', ') FROM memberships m JOIN collections c ON c.id = m.collection_id
                 WHERE m.item_id = i.id) AS cols
                FROM items i JOIN analysis a ON a.item_id = i.id"""


def item_text(row) -> str:
    parts = [row["title"], row["summary"], ", ".join(json.loads(row["tags"])) if row["tags"] else "",
             row["item_title"], row["author"] if row["item_title"] else "",  # "Title by Author" matters for books
             # the user's own collection/board/shelf/playlist names: the only words a bare image has
             f"Saved in: {row['cols']}" if row["cols"] else "",
             row["text"], row["transcript"], row["ocr"]]
    return "\n".join(p for p in parts if p and p.strip())


def load_e5(device=DEVICE):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(E5, device=device)
    m.max_seq_length = 512
    if device == "cuda":
        m.half()
    return m


def stage_text(con):
    rows = con.execute(TEXT_QUERY + " WHERE a.text_emb IS NULL AND a.transcript IS NOT NULL AND a.ocr IS NOT NULL").fetchall()
    if not rows:
        return
    model = load_e5()
    docs = ["passage: " + (item_text(r) or "(no text)") for r in rows]
    embs = model.encode(docs, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
    for r, e in zip(rows, embs):
        con.execute("UPDATE analysis SET text_emb=? WHERE item_id=?", (db.to_blob(e), r["id"]))
    con.commit()
    del model
    free()


DEFAULT_TOPICS = Path(__file__).parent / "topics.txt"
USER_TOPICS = db.DATA_DIR / "topics.txt"  # written by the Settings menu; overrides the default
BOOKS = "books & reading"


def topic_list() -> list[str]:
    f = USER_TOPICS if USER_TOPICS.exists() else DEFAULT_TOPICS
    return [t.strip() for t in f.read_text().splitlines() if t.strip() and not t.startswith("#")]


def stage_topics(con):
    """Broad topics for the topic filter: the topic closest to the item's LLM title + tags (or its own
    text) by e5 similarity, plus any almost as close. Tested better than asking the 1.7B LLM, which
    tends to pick the first entries of the list. Recomputed for everything when topics.txt changes."""
    topics = topic_list()
    version = hashlib.sha1("\n".join(topics).encode()).hexdigest()[:12]
    if db.get_meta(con, "topics_version") != version:
        con.execute("UPDATE analysis SET topics=NULL")
        db.set_meta(con, "topics_version", version)
        con.commit()
    rows = con.execute(TEXT_QUERY.replace("SELECT ", "SELECT i.kind, a.visual_emb, ", 1)
                       + " WHERE a.topics IS NULL AND a.transcript IS NOT NULL AND a.ocr IS NOT NULL").fetchall()
    if not rows:
        return
    # items without words (e.g. a bare Pinterest image) are matched by picture: SigLIP image vs "a photo about <topic>"
    wordless = [len("".join((r[k] or "").strip() for k in ("item_title", "text", "transcript", "ocr"))) < 15
                and r["visual_emb"] is not None for r in rows]
    sims = [None] * len(rows)
    if not all(wordless):
        model = load_e5()
        t = model.encode(["passage: " + x for x in topics], normalize_embeddings=True)
        idx = [i for i, w in enumerate(wordless) if not w]
        short = [f"{rows[i]['title']}. {', '.join(json.loads(rows[i]['tags']))}" if rows[i]["tags"] and rows[i]["title"]
                 else item_text(rows[i])[:500] or "(no text)" for i in idx]
        for i, sim in zip(idx, model.encode(["query: " + s for s in short], batch_size=32, normalize_embeddings=True) @ t.T):
            sims[i] = (sim, 0.005)
        del model
    if any(wordless):
        enc = Siglip()
        t = np.stack([enc.text(f"a photo about {x}") for x in topics])
        for i, w in enumerate(wordless):
            if w:
                sims[i] = (db.from_blob(rows[i]["visual_emb"]) @ t.T, 0.002)
        del enc
    for r, (sim, margin) in zip(rows, sims):
        best = [topics[i] for i in sim.argsort()[::-1][:3] if sim[i] >= sim.max() - margin]
        if r["kind"] == "book" and BOOKS in topics and BOOKS not in best:
            best = [BOOKS] + best[:2]
        con.execute("UPDATE analysis SET topics=? WHERE item_id=?", (json.dumps(best), r["id"]))
    con.commit()
    free()


STAGES = {"thumbs": stage_thumbs, "frames": stage_frames, "speech": stage_speech,
          "ocr": stage_ocr, "visual": stage_visual, "text": stage_text, "topics": stage_topics}


def run(only: list[str] | None = None, skip: list[str] | None = None):
    con = db.connect()
    ensure_rows(con)
    con.commit()
    for name, fn in STAGES.items():
        if (only and name not in only) or (skip and name in skip):
            continue
        print(f"[{name}]")
        fn(con)
        con.commit()
    print(f"\nProcessed on {DEVICE}.")
