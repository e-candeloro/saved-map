"""A small LLM writes an English title, summary and tags for each item from its text, transcript and
on-screen text. The result feeds the topic embedding, search, cluster labels and topics.
Default: Qwen3-1.7B on local Ollama; any OpenAI-compatible endpoint via config.toml.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from . import config, db, llm, process


class Description(BaseModel):
    title: str = Field(description="what the item is about, in English, max 8 words, no emoji")
    summary: str = Field(description="1-2 plain English sentences with the actual content or advice")
    tags: list[str] = Field(description="2-6 short lowercase English topic tags, spaces between words, not hashtags")


SYSTEM = """You describe things people saved on social platforms (Instagram posts, Pinterest pins,
Goodreads books) so they can be found and grouped later. You always write in English: when the item is
in Italian or another language, translate. Never answer in the item's language.
Use the title, text, speech transcript and on-screen text (OCR, often noisy: words glued or misspelled).
Ignore hashtag spam, calls to comment/follow/share and sponsor plugs. Do not invent facts:
if there is almost no text, keep the summary to what the text literally says.
- title: what the item is about, in English, max 8 words, no emoji. Write a real title even when the item has none.
- summary: 1-2 plain English sentences (max 40 words) with the actual content or advice
- tags: 2-6 short lowercase English topic tags with spaces between words, not hashtags,
  e.g. "friendship", "book recommendations", "pasta recipe".
"""

# Most posts are Italian or English. On all-Italian posts the small model sometimes answers in Italian.
ITALIAN = re.compile(r"\b(il|la|che|di|per|una|sono|della|non|un|con|alla|del)\b", re.I)


def clip(s: str | None, n: int) -> str:
    s = (s or "").strip()
    return (s[:n] + "…") if len(s) > n else s


def kind_of(row) -> str:
    if row["kind"] != "post":
        return row["kind"]
    mt = json.loads(row["details"] or "{}").get("media_type")
    return {1: "photo", 2: "video/reel", 8: "carousel"}.get(mt, "post")


def prompt(row) -> str:
    fields = [("Platform", row["source"]), ("Type", kind_of(row)), ("Author", row["author"]),
              ("Name", clip(row["title"], 200)), ("Text", clip(row["text"], 1500)),
              ("Transcript", clip(row["transcript"], 2500)), ("On-screen text", clip(row["ocr"], 1200))]
    return "\n".join(f"{k}: {v}" for k, v in fields if v) + "\n\nDescribe this item in English."


def has_text(row) -> bool:
    return len("".join((row[k] or "").strip() for k in ("title", "text", "transcript", "ocr"))) >= 15


def describe(cl, ep, row) -> Description | None:
    if not has_text(row):  # an image with no words: a small LLM can only guess, so don't ask it
        return Description(title="", summary="", tags=[])
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(row)}]
    out = llm.structured(cl, ep, messages, Description)
    if out and len(ITALIAN.findall(out.summary)) >= 5:  # one follow-up turn: translate its own answer
        messages += [{"role": "assistant", "content": out.model_dump_json()},
                     {"role": "user", "content": "That is in Italian. Rewrite the same JSON with title, summary and tags translated into English."}]
        out = llm.structured(cl, ep, messages, Description) or out
    if out:
        out.tags = [t.strip().lower().lstrip("#") for t in out.tags if t.strip()][:6]
    return out


def progress(done, total, t0):
    rate = done / (time.time() - t0)
    print(f"  {done}/{total}  {rate * 60:.0f}/min  eta {(total - done) / rate / 60:.0f} min", end="\r")


def run(limit: int | None = None):
    cfg = config.load()
    ep = cfg.models.llm
    con = db.connect()
    rows = con.execute("""SELECT i.id, i.source, i.kind, i.author, i.title, i.text, i.details, a.transcript, a.ocr
                          FROM items i JOIN analysis a ON a.item_id = i.id
                          WHERE a.summary IS NULL AND a.transcript IS NOT NULL AND a.ocr IS NOT NULL
                          ORDER BY i.source, i.saved_pos""").fetchall()[:limit]
    if not rows:
        print("Nothing to refine.")
        return
    llm.ensure_ollama(ep)
    cl = llm.client(ep)
    print(f"Describing {len(rows)} items with {ep.model}")
    t0 = time.time()
    with ThreadPoolExecutor(2) as pool:  # Ollama queues requests; two keep the GPU busy between answers
        for n, (row, out) in enumerate(zip(rows, pool.map(lambda r: describe(cl, ep, r), rows)), 1):
            if out:
                con.execute("UPDATE analysis SET title=?, summary=?, tags=?, text_emb=NULL, topics=NULL WHERE item_id=?",
                            (out.title.strip(), out.summary.strip(), json.dumps(out.tags), row["id"]))
                con.commit()
            progress(n, len(rows), t0)
    print("\nRe-embedding described items")
    process.stage_text(con)
    process.stage_topics(con)
