"""2D map + clusters for three views of the same items.

  visual -> what posts look like (SigLIP2)
  topic  -> what posts are about (caption + transcript + on-screen text)
  mixed  -> both, equally weighted
Clusters come from HDBSCAN on a 5D UMAP; labels are each cluster's most distinctive words.
"""
import json
import re

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.neighbors import NearestNeighbors
from stop_words import get_stop_words

from . import db
from .process import TEXT_QUERY, item_text

LAYOUT_PATH = db.DATA_DIR / "layout.json"
STOP = sorted(set(get_stop_words("english")) | set(get_stop_words("italian")) | {
    "the", "and", "link", "bio", "follow", "comment", "comments", "like", "share", "save", "post", "reel",
    "seguimi", "commenta", "salva", "condividi", "https", "www", "com"})


def umap(x, dim, seed=42):
    from umap import UMAP
    n = len(x)
    return UMAP(n_components=dim, n_neighbors=min(15, n - 1), min_dist=0.05 if dim == 2 else 0.0,
                metric="cosine", random_state=seed).fit_transform(x)


def labels_for(texts, assign, tags=None):
    """c-TF-IDF: terms frequent in a cluster but rare in the others.
    Terms are the LLM tags when available, otherwise words of the post text."""
    clusters = sorted(set(assign) - {-1})
    if not clusters:
        return {}
    if tags:
        docs = ["|".join(t for t, a in zip(tags, assign) if a == c) for c in clusters]
        vec = CountVectorizer(tokenizer=lambda d: [t for t in d.split("|") if t], token_pattern=None, lowercase=False,
                              max_df=0.9 if len(docs) > 3 else 1.0)
    else:
        docs = [" ".join(t for t, a in zip(texts, assign) if a == c) for c in clusters]
        vec = CountVectorizer(stop_words=STOP, token_pattern=r"(?u)#?\b[^\W\d_]{3,}\b", max_df=0.9 if len(docs) > 3 else 1.0)
    try:
        tf = vec.fit_transform(docs).toarray().astype(float)
    except ValueError:
        return {c: "misc" for c in clusters}
    words = vec.get_feature_names_out()
    tf /= tf.sum(1, keepdims=True) + 1e-9
    idf = np.log(1 + tf.shape[0] / (1 + (tf > 0).sum(0)))
    score = tf * idf
    # a cluster whose terms all appear everywhere scores 0: fall back to its most frequent terms
    return {c: " · ".join(words[i] for i in score[k].argsort()[::-1][:3] if score[k, i] > 0)
            or " · ".join(words[i] for i in tf[k].argsort()[::-1][:3] if tf[k, i] > 0) or "misc"
            for k, c in enumerate(clusters)}


def clusters(u):
    """HDBSCAN, then attach leftover points that sit as close to a cluster as its own members do."""
    n = len(u)
    # max_cluster_size stops HDBSCAN from settling on 2-3 giant clusters (e.g. Italian vs English)
    # min size ~0.5% of items: small coherent groups (a 14-pin board) can stand alone; tested against
    # board/collection purity (0.27 -> 0.37) and fewer unclustered items, without fragmenting (n//300 gave 77 clusters)
    assign = HDBSCAN(min_cluster_size=max(8, n // 200), max_cluster_size=max(20, n // 8),
                     min_samples=1, copy=True).fit_predict(u)
    member, noise = assign >= 0, assign < 0
    if member.sum() > 1 and noise.any():
        nn = NearestNeighbors(n_neighbors=2).fit(u[member])
        typical = np.percentile(nn.kneighbors(u[member])[0][:, 1], 95)  # members' distance to their nearest member
        dist, idx = nn.kneighbors(u[noise], n_neighbors=1)
        near = dist[:, 0] <= typical
        assign[np.flatnonzero(noise)[near]] = assign[member][idx[near, 0]]
    return assign


def run(only_if_changed: bool = False):
    con = db.connect()
    rows = con.execute(TEXT_QUERY.replace("SELECT ", "SELECT a.visual_emb, a.text_emb, ", 1)
                       + " WHERE a.visual_emb IS NOT NULL AND a.text_emb IS NOT NULL ORDER BY i.id").fetchall()
    ids = [r["id"] for r in rows]
    if only_if_changed and LAYOUT_PATH.exists():
        old = json.loads(LAYOUT_PATH.read_text())
        if set(next(iter(old.values()), {}).get("points", {})) == set(ids):
            print("Map unchanged.")
            return
    if len(rows) < 10:
        print(f"Only {len(rows)} processed items; need at least 10 to build a map.")
        return
    texts = [re.sub(r"\s+", " ", item_text(r).lower()) for r in rows]
    # label terms: the LLM tags, or for items without any (bare images) their topics and collection names
    tags = ["|".join(json.loads(r["tags"]) if r["tags"] and json.loads(r["tags"])
                     else json.loads(r["topics"] or "[]") + [x.strip().lower() for x in (r["cols"] or "").split(",") if x.strip()])
            for r in rows]
    use_tags = sum(bool(t) for t in tags) >= 0.5 * len(rows)
    vis = np.stack([db.from_blob(r["visual_emb"]) for r in rows])
    txt = np.stack([db.from_blob(r["text_emb"]) for r in rows])
    views = {"mixed": np.hstack([vis, txt]) / np.sqrt(2), "visual": vis, "topic": txt}

    layout = {}
    for name, x in views.items():
        xy = umap(x, 2)
        xy = xy - xy.mean(0)
        xy = xy @ np.linalg.svd(xy, full_matrices=False)[2].T  # longest spread along x; the frontend turns it to the window
        lo, hi = np.percentile(xy, [0.5, 99.5], axis=0)  # 0..1 for the frontend; a few outliers sit on the edge
        xy = np.clip((xy - lo) / (hi - lo + 1e-9), 0, 1)
        aspect = float((hi - lo)[0] / ((hi - lo)[1] + 1e-9))  # width/height before the 0..1 scaling
        assign = clusters(umap(x, 5))
        labels = labels_for(texts, assign, tags if use_tags else None)
        layout[name] = {
            "points": {i: [round(float(p[0]), 4), round(float(p[1]), 4), int(a)] for i, p, a in zip(ids, xy, assign)},
            "clusters": {int(k): v for k, v in labels.items()},
            "aspect": round(aspect, 3),
        }
        print(f"{name}: {len(labels)} clusters, {int((assign == -1).sum())} unclustered")
    LAYOUT_PATH.write_text(json.dumps(layout))
    print("Saved", LAYOUT_PATH)
