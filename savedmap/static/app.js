// SavedMap frontend: filters, grid, map, viewer, update. Vanilla JS, no build step.
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = n => n.toLocaleString("en-US");

// ---------- icons (Lucide data, rendered inline: one size, one stroke) ----------
function icon(name, size = 16) {
  const key = name.split("-").map(w => w[0].toUpperCase() + w.slice(1)).join("");
  const node = ICONS[key];  // static/icons.js: only the icons this app uses (scripts/build_ui.sh)
  if (!node) return "";
  const kids = node.map(([tag, attrs]) => `<${tag} ${Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(" ")}/>`).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="shrink-0">${kids}</svg>`;
}
const paintIcons = (root = document) => root.querySelectorAll("[data-icon]").forEach(el => { el.innerHTML = icon(el.dataset.icon); el.classList.add("inline-flex"); });

const PLATFORMS = {
  instagram: { name: "Instagram", icon: "camera", color: "#c13584", collections: "Collections" },
  pinterest: { name: "Pinterest", icon: "pin", color: "#d0202e", collections: "Boards" },
  youtube: { name: "YouTube", icon: "circle-play", color: "#e5484d", collections: "Playlists" },
  goodreads: { name: "Goodreads", icon: "book-open", color: "#8a6a3f", collections: "Shelves" },
  karakeep: { name: "Karakeep", icon: "bookmark", color: "#3f7fd8", collections: "Lists" },
};
const KIND = { post: "post", pin: "pin", book: "book", video: "video", bookmark: "bookmark" };
// muted, distinguishable cluster colours (map frames and dots only)
const PALETTE = ["#4e79a7", "#e15759", "#59a14f", "#b07aa1", "#f28e2b", "#76b7b2", "#9c755f", "#edc948", "#ff9da7", "#5f8f3a", "#8c6bb1", "#d37295", "#499894", "#bc8a5f"];
const color = c => c < 0 ? "#9a9a9a" : PALETTE[c % PALETTE.length];

// ---------- state (kept in the URL so Back works and views can be bookmarked) ----------
const S = { items: [], byId: {}, cols: [], colById: {}, layout: {}, results: null,
            tab: "grid", mode: "mixed", platform: null, topic: null, col: null, cluster: null, removed: false, q: "" };
const URL_KEYS = ["tab", "mode", "platform", "topic", "col", "cluster", "removed", "q"];

function readURL() {
  const p = new URLSearchParams(location.hash.slice(1));
  S.tab = p.get("tab") === "map" ? "map" : "grid";
  S.mode = ["mixed", "visual", "topic"].includes(p.get("mode")) ? p.get("mode") : "mixed";
  S.platform = p.get("platform"); S.topic = p.get("topic"); S.col = p.get("col");
  S.cluster = p.has("cluster") ? +p.get("cluster") : null;
  S.removed = p.get("removed") === "1"; S.q = p.get("q") || "";
}
function writeURL(push = true) {
  const p = new URLSearchParams();
  for (const k of URL_KEYS) {
    const v = S[k];
    if (v === null || v === "" || v === false || (k === "tab" && v === "grid") || (k === "mode" && v === "mixed")) continue;
    p.set(k, v === true ? "1" : v);
  }
  const hash = p.toString() ? "#" + p : location.pathname;
  push ? history.pushState(null, "", hash) : history.replaceState(null, "", hash);
}

// ---------- data ----------
async function load() {
  const d = await (await fetch("/api/data")).json();
  for (const p of d.items) p.thumb = p.thumb ? `/thumbs/${p.id.replace(":", "/")}.webp` : null;
  S.items = d.items; S.cols = d.collections;
  S.byId = Object.fromEntries(S.items.map(p => [p.id, p]));
  S.colById = Object.fromEntries(S.cols.map(c => [c.id, c]));
}
async function loadLayout() {  // the map arrives after the first paint; the grid never waits for it
  S.layout = await (await fetch("/api/layout")).json();
  viewKey = ""; renderSide();
  if (S.tab === "map") invalidate();
}

// ---------- filtering ----------
const UNSORTED = "none";
function cluster(p) { return S.layout[S.mode]?.points[p.id]?.[2]; }
function passes(p, except) {
  if (!S.removed && p.removed) return false;
  if (except !== "platform" && S.platform && p.source !== S.platform) return false;
  if (except !== "topic" && S.topic && !p.topics.includes(S.topic)) return false;
  if (except !== "col" && S.col && (S.col === UNSORTED ? p.collections.length : !p.collections.includes(S.col))) return false;
  if (except !== "cluster" && S.cluster !== null && cluster(p) !== S.cluster) return false;
  return true;
}
function visible() {
  const base = S.results ? S.results.map(r => S.byId[r.id]).filter(Boolean) : S.items;
  return base.filter(p => passes(p));
}
function countBy(except, key) {
  const n = {};
  for (const p of S.items) if (passes(p, except)) for (const k of [].concat(key(p))) n[k] = (n[k] || 0) + 1;
  return n;
}

// ---------- sidebar ----------
function row(attrs, pressed, label, n, lead = "") {
  return `<button class="row" ${attrs} aria-pressed="${pressed}">${lead}<span class="truncate">${esc(label)}</span><span class="n">${n ?? 0}</span></button>`;
}
const dot = c => `<span class="size-2 shrink-0 rounded-full" style="background:${c}"></span>`;

function renderSide() {
  const out = [];
  const plat = countBy("platform", p => p.source);
  const sources = Object.keys(PLATFORMS).filter(s => S.items.some(p => p.source === s));
  out.push(`<div class="section-label">Platforms</div>`);
  out.push(row(`data-f="platform" data-v=""`, !S.platform, "Everything", Object.values(plat).reduce((a, b) => a + b, 0), `<span class="text-fg3">${icon("layers")}</span>`));
  for (const s of sources) out.push(row(`data-f="platform" data-v="${s}"`, S.platform === s, PLATFORMS[s].name, plat[s],
    `<span class="text-fg3">${icon(PLATFORMS[s].icon)}</span>`));
  for (const s of Object.keys(PLATFORMS).filter(s => !sources.includes(s)))
    out.push(`<div class="flex h-8 items-center gap-2 px-2 text-sm text-fg3">${icon(PLATFORMS[s].icon)}<span>${PLATFORMS[s].name}</span><span class="ml-auto text-xs">not connected</span></div>`);

  const top = countBy("topic", p => p.topics);
  const topics = Object.entries(top).sort((a, b) => b[1] - a[1]);
  if (topics.length) {
    out.push(`<div class="section-label">Topics</div>`);
    const shown = S.allTopics ? topics : topics.filter(([t], i) => i < 8 || t === S.topic);
    for (const [t, n] of shown) out.push(row(`data-f="topic" data-v="${esc(t)}"`, S.topic === t, t[0].toUpperCase() + t.slice(1), n));
    if (topics.length > 8) out.push(`<button class="row text-fg3" data-more>${icon(S.allTopics ? "chevron-up" : "chevron-down")}<span>${S.allTopics ? "Fewer topics" : `All ${topics.length} topics`}</span></button>`);
  }

  const col = countBy("col", p => p.collections.length ? p.collections : [UNSORTED]);
  for (const s of sources) {
    const cs = S.cols.filter(c => c.source === s && (col[c.id] || S.col === c.id));
    if (!cs.length) continue;
    out.push(`<div class="section-label flex items-center gap-2">${dot(PLATFORMS[s].color)}${PLATFORMS[s].collections}</div>`);
    for (const c of cs) out.push(row(`data-f="col" data-v="${esc(c.id)}"`, S.col === c.id, c.name, col[c.id]));
  }
  if (col[UNSORTED]) out.push(row(`data-f="col" data-v="${UNSORTED}"`, S.col === UNSORTED, "Not in a collection", col[UNSORTED]));

  const L = S.layout[S.mode];
  out.push(`<div class="section-label">Clusters on the map</div>`);
  if (!L) out.push(`<p class="px-2 text-sm text-fg3">Run <code class="font-mono">savedmap cluster</code> to build the map.</p>`);
  else {
    const cl = countBy("cluster", p => cluster(p) ?? []);
    const rows = Object.entries(L.clusters).filter(([id]) => cl[id] || S.cluster === +id).sort((a, b) => (cl[b[0]] || 0) - (cl[a[0]] || 0));
    if (cl[-1]) rows.push(["-1", "Not in a cluster"]);
    for (const [id, label] of rows) out.push(row(`data-f="cluster" data-v="${id}"`, S.cluster === +id, label, cl[id], dot(color(+id))));
  }
  if (S.items.some(p => p.removed)) {
    const n = S.items.filter(p => p.removed).length;
    out.push(`<div class="section-label">Archive</div>`);
    out.push(row(`data-f="removed" data-v="1"`, S.removed, "Show no longer saved", n, `<span class="text-fg3">${icon(S.removed ? "eye" : "eye-off")}</span>`));
  }
  $("#side").innerHTML = out.join("");
}

// ---------- status line + active filter chips ----------
function renderChips(n) {
  const chips = [];
  const chip = (f, label) => chips.push(`<button class="chip" data-clear="${f}" aria-label="Remove filter ${esc(label)}">${esc(label)}${icon("x", 12)}</button>`);
  if (S.platform) chip("platform", PLATFORMS[S.platform].name);
  if (S.topic) chip("topic", S.topic);
  if (S.col) chip("col", S.col === UNSORTED ? "Not in a collection" : S.colById[S.col]?.name || S.col);
  if (S.cluster !== null) chip("cluster", S.cluster < 0 ? "Not in a cluster" : S.layout[S.mode]?.clusters[S.cluster] || "cluster");
  if (S.removed) chip("removed", "Including no longer saved");
  if (S.q) chips.unshift(`<button class="chip" data-clear="q" aria-label="Clear search">“${esc(S.q)}”${icon("x", 12)}</button>`);
  $("#resetFilters").disabled = !chips.length;
  $("#chips").innerHTML = chips.join("");
  $("#status").innerHTML = S.results
    ? `<span class="font-mono tabular-nums">${fmt(n)}</span> results for “${esc(S.q)}”`
    : `<span class="font-mono tabular-nums">${fmt(n)}</span> ${n === 1 ? "item" : "items"}`;
}

// ---------- grid ----------
function tile(p, n = 99) {
  const video = p.kind === "video" || p.video, multi = p.n_media > 1;
  const badge = video ? icon("play", 12) : multi ? `${icon("images", 12)}<span class="font-mono">${p.n_media}</span>` : p.kind === "book" ? icon("book-open", 12) : "";
  const label = (p.title || p.name || `${KIND[p.kind]} by ${p.author || "unknown"}`) + (multi && !video ? `, ${p.n_media} images` : "");
  return `<button data-id="${esc(p.id)}" class="group relative aspect-square overflow-hidden rounded-lg bg-raised ${p.removed ? "opacity-50" : ""}" title="${esc(label)}" aria-label="${esc(label)}">
    ${p.thumb ? `<img ${n < 12 ? `loading="eager"${n === 0 ? ' fetchpriority="high"' : ""}` : 'loading="lazy"'} decoding="async" width="320" height="320" src="${p.thumb}" alt="" class="size-full object-cover transition-transform duration-300 ease-out group-hover:scale-[1.02]">`
              : `<span class="flex size-full items-center justify-center p-3 text-center text-xs text-fg2">${esc(label)}</span>`}
    ${badge ? `<span aria-hidden="true" class="absolute top-2 right-2 inline-flex h-5 items-center gap-1 rounded-md bg-black/60 px-1.5 text-xs text-white">${badge}</span>` : ""}
    ${S.platform || !multiPlatform ? "" : `<span class="absolute bottom-2 left-2 size-2 rounded-full ring-2 ring-black/30" style="background:${PLATFORMS[p.source]?.color}"></span>`}
  </button>`;
}

function emptyMessage() {
  if (!S.items.length) return `Nothing here yet. Enable a platform in <code class="font-mono">data/config.toml</code>, then press Update, or run <code class="font-mono">/savedmap-setup</code> in Claude Code.`;
  return `No items match. <button class="text-accent underline-offset-2 hover:underline" data-clear="all">Clear all filters</button>`;
}

let multiPlatform = false;
function render() {
  const list = visible();
  multiPlatform = new Set(S.items.map(p => p.source)).size > 1;
  renderChips(list.length);
  document.querySelectorAll(".tab").forEach(b => b.setAttribute("aria-selected", b.dataset.tab === S.tab));
  $("#mode").value = S.mode;
  $("#mode").classList.toggle("hidden", S.tab !== "map");
  const none = !list.length;
  $("#empty").classList.toggle("hidden", !none);
  if (none) $("#empty").innerHTML = emptyMessage();
  $("#grid").classList.toggle("hidden", S.tab !== "grid" || none);
  $("#map").classList.toggle("hidden", S.tab !== "map");
  $("#mapNote").classList.toggle("hidden", S.tab !== "map");
  $("#mapCtl").classList.toggle("hidden", S.tab !== "map");
  $("#mapCtl").classList.toggle("flex", S.tab === "map");
  $("#spacing").classList.toggle("hidden", S.tab !== "map");
  if (S.tab === "grid") {
    $("#grid").innerHTML = list.slice(0, 120).map((p, n) => tile(p, n)).join("");
    pending = list.slice(120);  // the rest renders as you scroll (keeps the DOM small)
  } else invalidate();
}
let pending = [];
new IntersectionObserver(entries => {
  if (entries[0].isIntersecting && S.tab === "grid" && pending.length)
    $("#grid").insertAdjacentHTML("beforeend", pending.splice(0, 120).map(p => tile(p)).join(""));
}, { root: $("#view"), rootMargin: "1200px" }).observe($("#more"));

// ---------- map ----------
// All thumbnails are drawn once into an offscreen layer (with a margin around the viewport). Panning
// and zooming only move or scale that layer, one drawImage per frame; the layer is re-rendered when
// the view settles, when filters change, and at most every 400 ms while thumbnails arrive.
const cv = $("#map"), ctx = cv.getContext("2d"), imgs = {};
const layer = document.createElement("canvas"), lctx = layer.getContext("2d");
const V = { x: 0, y: 0, k: 1 };  // current pan/zoom
let LV = null;                    // pan/zoom the layer was rendered with; null = stale
const PAD = 60, MARGIN = 0.25;
let theme = {};
function readTheme() {
  const c = getComputedStyle(document.documentElement);
  theme = { bg: c.getPropertyValue("--bg").trim(), raised: c.getPropertyValue("--raised").trim() };
}

let viewKey = "", mv = { show: new Set(), entries: [] };
function mapView() {  // visible set and draw order, recomputed only when filters or data change
  const key = [S.mode, S.platform, S.topic, S.col, S.cluster, S.removed, S.results ? S.q + S.results.length : "", S.items.length].join("|");
  if (key !== viewKey) {
    viewKey = key;
    const pts = S.layout[S.mode]?.points || {}, show = new Set(visible().map(p => p.id));
    const entries = Object.entries(pts).filter(([id]) => S.byId[id] && (S.removed || !S.byId[id].removed))
      .sort(([a], [b]) => show.has(a) - show.has(b));  // dimmed ones underneath
    mv = { show, entries };
  }
  return mv;
}

let drawQueued = false, settleTimer = null, thumbTimer = null, interacting = false;
function requestDraw() {
  if (!drawQueued) { drawQueued = true; requestAnimationFrame(() => { drawQueued = false; drawMap(); }); }
}
function invalidate() { LV = null; requestDraw(); }
function settle() {  // re-render the layer once pan/zoom has stopped
  interacting = true;
  clearTimeout(settleTimer);
  settleTimer = setTimeout(() => { interacting = false; invalidate(); }, 150);
}

const thumbQueue = [];
let thumbsLoading = 0, thumbsDone = 0;
function thumbImg(p) {  // queued (browsers fail thousands of parallel requests), small square crop for memory
  if (!(p.id in imgs) && p.thumb) { imgs[p.id] = null; thumbQueue.push(p); pumpThumbs(); }
  return imgs[p.id];
}
function pumpThumbs() {
  while (thumbsLoading < 8 && thumbQueue.length) {
    const p = thumbQueue.shift(); thumbsLoading++;
    fetch(p.thumb).then(r => r.ok ? r.blob() : Promise.reject()).then(createImageBitmap).then(full => {
      const s = Math.min(full.width, full.height);
      return createImageBitmap(full, (full.width - s) / 2, (full.height - s) / 2, s, s, { resizeWidth: 96, resizeHeight: 96, resizeQuality: "medium" })
        .finally(() => full.close());
    }).then(bm => {
      imgs[p.id] = bm; thumbsDone++;
      if (S.tab === "map" && !thumbTimer) thumbTimer = setTimeout(() => { thumbTimer = null; if (!interacting) invalidate(); }, 400);
    }).catch(() => delete imgs[p.id])  // retried on a later render
      .finally(() => { thumbsLoading--; pumpThumbs(); });
  }
}
function screen(q, v = V) {  // q: a position from positions(), in canvas pixels at zoom 1
  return [PAD + q[0] * v.k + v.x, PAD + q[1] * v.k + v.y];
}

// The layout is turned to match the window (landscape or portrait) and scaled evenly, stretched at most
// STRETCH to fill it. Spacing pushes apart items closer than a share of the average gap, then fits the
// map back in: dense clusters open up, empty space between clusters shrinks, and it never sprawls.
const STRETCH = 1.3, SPACING = { off: 0, low: 0.35, medium: 0.6, high: 0.85 };
let spacing = "medium";
try { const v = localStorage.getItem("spacing"); if (v in SPACING) spacing = v; } catch {}
let spread = {}, placed = {};
function positions() {
  const L = S.layout[S.mode], w = cv.width - 2 * PAD, h = cv.height - 2 * PAD;
  const a = L.aspect || w / h, swap = !!L.aspect && (a > 1) !== (w > h), A = swap ? 1 / a : a;  // older layouts: fill
  const u = Math.min(w / A, h), bw = Math.min(w, u * A * STRETCH), bh = Math.min(h, u * STRETCH), R = Math.sqrt(bw / bh);
  const key = [S.mode, swap, R.toFixed(2), spacing].join("|");
  if (spread.L !== L || spread.key !== key) {  // in a box of area 1 with the drawn map's shape
    const ids = Object.keys(L.points), xs = new Float64Array(ids.length), ys = new Float64Array(ids.length);
    ids.forEach((id, i) => { const p = L.points[id]; xs[i] = (swap ? p[1] : p[0]) * R; ys[i] = (swap ? p[0] : p[1]) / R; });
    if (SPACING[spacing] && ids.length > 1) { relax(xs, ys, SPACING[spacing] / Math.sqrt(ids.length)); refit(xs, ys, R, 1 / R); }
    spread = { L, key, ids, xs, ys };
  }
  const k2 = [key, w, h].join("|");
  if (placed.spread !== spread || placed.key !== k2) {
    const ox = (w - bw) / 2, oy = (h - bh) / 2, { ids, xs, ys } = spread, pos = {};
    ids.forEach((id, i) => { pos[id] = [ox + xs[i] / R * bw, oy + ys[i] * R * bh]; });
    placed = { spread, key: k2, pos };
  }
  return placed.pos;
}
function relax(xs, ys, d, rounds = 40) {  // move apart pairs closer than d (spatial hash of d-sized cells)
  const n = xs.length, inv = 1 / d, d2 = d * d;
  for (let r = 0; r < rounds; r++) {
    const grid = new Map();
    for (let i = 0; i < n; i++) {
      const k = Math.floor(xs[i] * inv) * 100003 + Math.floor(ys[i] * inv);
      (grid.get(k) || grid.set(k, []).get(k)).push(i);
    }
    let moved = 0;
    for (let i = 0; i < n; i++) {
      const cx = Math.floor(xs[i] * inv), cy = Math.floor(ys[i] * inv);
      for (let gx = cx - 1; gx <= cx + 1; gx++) for (let gy = cy - 1; gy <= cy + 1; gy++) {
        for (const j of grid.get(gx * 100003 + gy) || []) {
          if (j <= i) continue;
          let dx = xs[j] - xs[i], dy = ys[j] - ys[i], dd = dx * dx + dy * dy;
          if (dd >= d2) continue;
          if (dd < 1e-14) { dx = Math.cos(i + j) * 1e-6; dy = Math.sin(i + j) * 1e-6; dd = 1e-12; }  // stacked: split them
          const dist = Math.sqrt(dd), f = (d - dist) / dist / 2;
          xs[i] -= dx * f; ys[i] -= dy * f; xs[j] += dx * f; ys[j] += dy * f; moved++;
        }
      }
    }
    if (!moved) break;
  }
}
function refit(xs, ys, bw, bh) {  // scale evenly back into the bw x bh box, centred
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < xs.length; i++) { x0 = Math.min(x0, xs[i]); x1 = Math.max(x1, xs[i]); y0 = Math.min(y0, ys[i]); y1 = Math.max(y1, ys[i]); }
  const s = Math.min(bw / (x1 - x0 || 1), bh / (y1 - y0 || 1)), ox = (bw - (x1 - x0) * s) / 2, oy = (bh - (y1 - y0) * s) / 2;
  for (let i = 0; i < xs.length; i++) { xs[i] = ox + (xs[i] - x0) * s; ys[i] = oy + (ys[i] - y0) * s; }
}
$("#spacing").value = spacing;
$("#spacing").addEventListener("change", e => {
  spacing = e.target.value;
  try { localStorage.setItem("spacing", spacing); } catch {}
  invalidate();
});
const tileSize = (r, k = V.k) => Math.min(90, 34 * Math.sqrt(k)) * r;

function renderLayer() {
  const r = devicePixelRatio || 1, W = cv.width, H = cv.height, mx = Math.round(W * MARGIN), my = Math.round(H * MARGIN);
  if (layer.width !== W + 2 * mx || layer.height !== H + 2 * my) { layer.width = W + 2 * mx; layer.height = H + 2 * my; }
  else lctx.clearRect(0, 0, layer.width, layer.height);
  LV = { ...V, mx, my };
  const L = S.layout[S.mode], P = positions(), { show, entries } = mapView(), size = tileSize(r), half = size / 2;
  // Zoomed out, most tiles sit under others. Walk top-down and keep one tile per small grid cell:
  // the hidden ones are never drawn, so dense views cost about the same as sparse ones.
  const cell = size * 0.4, taken = new Set(), todo = [];
  for (let i = entries.length - 1; i >= 0; i--) {
    const [id, pt] = entries[i], [sx, sy] = screen(P[id]), x = sx + mx, y = sy + my;
    if (x < -size || y < -size || x > layer.width + size || y > layer.height + size) continue;
    const key = Math.floor(x / cell) * 65536 + Math.floor(y / cell);
    if (taken.has(key)) continue;
    taken.add(key); todo.push([id, pt, x, y]);
  }
  lctx.lineWidth = 2.5 * r;
  for (let i = todo.length - 1; i >= 0; i--) {
    const [id, pt, x, y] = todo[i];
    lctx.globalAlpha = show.has(id) ? 1 : 0.1;
    const im = thumbImg(S.byId[id]);
    if (im) lctx.drawImage(im, x - half, y - half, size, size);
    else { lctx.fillStyle = theme.raised; lctx.fillRect(x - half, y - half, size, size); }
    lctx.strokeStyle = color(pt[2]); lctx.strokeRect(x - half, y - half, size, size);
  }
  lctx.globalAlpha = 1;
  // cluster labels at centroids, biggest clusters first, skipping ones that would overlap
  const cent = {};
  for (const [id, [, , c]] of entries) if (c >= 0 && show.has(id)) { const [x, y] = P[id]; (cent[c] ||= [0, 0, 0]); cent[c][0] += x; cent[c][1] += y; cent[c][2]++; }
  lctx.font = `500 ${12 * r}px system-ui, sans-serif`; lctx.textAlign = "left"; lctx.textBaseline = "middle";
  const placed = [];
  for (const [c, [sx, sy, n]] of Object.entries(cent).sort((a, b) => b[1][2] - a[1][2])) {
    const t = L.clusters[c] || "", w = lctx.measureText(t).width + 24 * r, h = 22 * r, [cx, cy] = screen([sx / n, sy / n]);
    const x = mx + Math.min(Math.max(cx - w / 2, 4 * r), W - w - 4 * r), y = my + cy - half - h - 4 * r;
    if (placed.some(b => x < b[0] + b[2] && b[0] < x + w && y < b[1] + b[3] && b[1] < y + h)) continue;
    placed.push([x, y, w, h]);
    lctx.fillStyle = "rgb(20 20 21 / .82)"; lctx.beginPath(); lctx.roundRect(x, y, w, h, 6 * r); lctx.fill();
    lctx.fillStyle = color(+c); lctx.beginPath(); lctx.arc(x + 10 * r, y + h / 2, 3.5 * r, 0, 7); lctx.fill();
    lctx.fillStyle = "#ededed"; lctx.fillText(t, x + 18 * r, y + h / 2 + 0.5 * r);
  }
  const total = todo.length, loaded = todo.reduce((n, [id]) => n + !!imgs[id], 0);
  $("#mapNote").textContent = loaded < total ? `Loading thumbnails ${fmt(loaded)}/${fmt(total)}` : (matchMedia("(pointer: coarse)").matches ? "Pinch to zoom, drag to move" : "Scroll to zoom, drag to move");
}

function drawMap() {
  if (S.tab !== "map") return;
  const r = devicePixelRatio || 1, box = $("#view").getBoundingClientRect();
  const W = Math.round(box.width * r), H = Math.round(box.height * r);
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; LV = null; }
  if (!theme.bg) readTheme();  // Tailwind compiles its styles after this script first runs
  ctx.fillStyle = theme.bg; ctx.fillRect(0, 0, W, H);
  if (!S.layout[S.mode]) { $("#mapNote").textContent = "No map yet: run savedmap cluster"; return; }
  if (!LV) renderLayer();
  // layer pixel q was screen position q - margin at render time; map it through the pan/zoom change
  const s = V.k / LV.k;
  ctx.drawImage(layer, PAD + (-LV.mx - PAD - LV.x) * s + V.x, PAD + (-LV.my - PAD - LV.y) * s + V.y, layer.width * s, layer.height * s);
}
function hit(ev) {
  if (!S.layout[S.mode]) return null;
  const r = devicePixelRatio || 1, b = cv.getBoundingClientRect(), mx = (ev.clientX - b.left) * r, my = (ev.clientY - b.top) * r;
  const half = tileSize(r) / 2, P = positions(), { entries } = mapView();
  let best = null;
  for (const [id] of entries) {  // drawn last = on top
    const [x, y] = screen(P[id]);
    if (Math.abs(mx - x) < half && Math.abs(my - y) < half) best = id;
  }
  return best;
}
let drag = null;
const touches = new Map();  // active pointers, for pinch-zoom
let pinch = null;
cv.addEventListener("pointerdown", e => {
  touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (touches.size === 2) {
    const [a, b] = [...touches.values()];
    pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) }; drag = null; return;
  }
  drag = { x: e.clientX, y: e.clientY, moved: false };
});
cv.addEventListener("pointermove", e => {
  if (!touches.has(e.pointerId)) return;
  touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pinch && touches.size === 2) {
    const [a, b] = [...touches.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
    const r = devicePixelRatio || 1, box = cv.getBoundingClientRect();
    zoomAt(d / pinch.d, ((a.x + b.x) / 2 - box.left) * r - PAD, ((a.y + b.y) / 2 - box.top) * r - PAD);
    pinch.d = d;
  }
});
const lift = e => { touches.delete(e.pointerId); if (touches.size < 2) pinch = null; };
addEventListener("pointerup", lift);
addEventListener("pointercancel", lift);
addEventListener("pointerup", e => {
  if (drag && !drag.moved && e.target === cv) { const id = hit(e); if (id) openItem(id); }
  drag = null; cv.classList.remove("dragging");
});
cv.addEventListener("pointermove", e => {
  const r = devicePixelRatio || 1;
  if (pinch) return;
  if (drag) {
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) { drag.moved = true; cv.classList.add("dragging"); }
    V.x += dx * r; V.y += dy * r; drag.x = e.clientX; drag.y = e.clientY; $("#tip").classList.add("hidden"); requestDraw(); settle(); return;
  }
  const id = hit(e), tip = $("#tip");
  if (!id) { tip.classList.add("hidden"); return; }
  const p = S.byId[id], b = $("#view").getBoundingClientRect();
  if (tip.dataset.id !== id) {  // text only: no new elements for the Tailwind runtime to scan on every move
    tip.dataset.id = id;
    $("#tipTitle").textContent = p.title || p.name || "@" + p.author;
    $("#tipText").textContent = (p.summary || "").slice(0, 140);
  }
  tip.classList.remove("hidden");
  tip.style.left = Math.min(e.clientX - b.left + 14, b.width - 290) + "px"; tip.style.top = (e.clientY - b.top + 14) + "px";
});
cv.addEventListener("pointerleave", () => $("#tip").classList.add("hidden"));
function zoomAt(f, mx = cv.width / 2 - PAD, my = cv.height / 2 - PAD) {  // mx/my: canvas pixels minus padding
  const k = Math.min(30, Math.max(0.5, V.k * f)), g = k / V.k;
  V.x = mx - (mx - V.x) * g; V.y = my - (my - V.y) * g; V.k = k; requestDraw(); settle();
}
function resetView() { V.x = V.y = 0; V.k = 1; invalidate(); }
$("#mapCtl").addEventListener("click", e => {
  const b = e.target.closest("[data-zoom]"); if (!b) return;
  b.dataset.zoom === "reset" ? resetView() : zoomAt(b.dataset.zoom === "in" ? 1.5 : 1 / 1.5);
});
cv.addEventListener("wheel", e => {
  e.preventDefault();
  const r = devicePixelRatio || 1, b = cv.getBoundingClientRect();
  zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, (e.clientX - b.left) * r - PAD, (e.clientY - b.top) * r - PAD);
}, { passive: false });
addEventListener("resize", () => S.tab === "map" && invalidate());

// ---------- viewer ----------
let current = null;
function stars(n) { return n ? `<span class="text-accent" aria-label="${n} of 5 stars">${"★".repeat(n)}</span><span class="text-fg3">${"★".repeat(5 - n)}</span>` : ""; }
function section(title, body, open = false) {
  return body ? `<details class="border-t border-line py-3" ${open ? "open" : ""}><summary class="cursor-pointer text-sm text-fg2 hover:text-fg">${title}</summary><div class="mt-2 text-sm whitespace-pre-wrap text-fg">${esc(body)}</div></details>` : "";
}
const itemCache = new Map();
async function openItem(id) {
  const base = S.byId[id]; if (!base) return;
  current = id;
  if (!itemCache.has(id)) {
    const [det, rel] = await Promise.all([fetch("/api/item/" + encodeURIComponent(id)).then(r => r.json()),
                                          fetch("/api/related/" + encodeURIComponent(id)).then(r => r.json())]);
    itemCache.set(id, { ...det, related: rel.results });
  }
  if (current !== id) return;  // the user moved on while it loaded
  const det = itemCache.get(id);
  const related = det.related.map(r => S.byId[r]).filter(Boolean);
  const p = { ...base, ...det, details: { ...base.details, ...det.details } };
  const d = $("#dlg"), list = visible(), pos = list.findIndex(x => x.id === id);
  const plat = PLATFORMS[p.source] || { name: p.source, color: "#999" };
  const cols = p.collections.map(c => S.colById[c]?.name).filter(Boolean);
  const date = p.created_at ? new Date(p.created_at * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "";
  let i = 0;
  const stage = () => {
    if (p.kind === "video") {  // YouTube: embedded player (needs internet); the stored thumbnail is the fallback
      const vid = new URL(p.url).searchParams.get("v");
      return navigator.onLine ? `<iframe src="https://www.youtube-nocookie.com/embed/${esc(vid)}?rel=0" title="${esc(p.name || "YouTube video")}" class="aspect-video w-full" allow="encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe>`
        : `<a href="${esc(p.url)}" target="_blank" rel="noopener" class="flex max-h-full"><img src="${p.thumb}" alt="" class="max-h-full max-w-full object-contain"></a>`;
    }
    if (p.kind === "book") return p.cover || p.thumb ? `<img src="${p.cover || p.thumb}" alt="Cover of ${esc(p.name)}" class="max-h-full max-w-full rounded-md object-contain shadow-lg">` : `<span class="text-fg3">${icon("book-open", 48)}</span>`;
    const m = p.media[i];
    if (!m) return p.thumb ? `<img src="${p.thumb}" alt="" class="max-h-full max-w-full object-contain">` : "";
    const el = m.kind === "video" ? `<video src="${m.url}" controls autoplay playsinline class="max-h-full max-w-full"></video>` : `<img src="${m.url}" alt="" class="max-h-full max-w-full object-contain">`;
    const nav = p.media.length > 1 ? `<button class="slide absolute top-1/2 left-3 inline-flex size-9 -translate-y-1/2 items-center justify-center rounded-full bg-black/55 text-white" data-step="-1" aria-label="Previous image">${icon("chevron-left")}</button>
      <button class="slide absolute top-1/2 right-3 inline-flex size-9 -translate-y-1/2 items-center justify-center rounded-full bg-black/55 text-white" data-step="1" aria-label="Next image">${icon("chevron-right")}</button>
      <span class="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-md bg-black/55 px-2 font-mono text-xs text-white">${i + 1}/${p.media.length}</span>` : "";
    return el + nav;
  };
  const heading = p.kind === "book" || p.kind === "video" ? p.name || p.title : (p.title || p.name || `${KIND[p.kind]} by ${p.author}`);
  const dur = p.details.duration ? `${Math.floor(p.details.duration / 60)}:${String(Math.round(p.details.duration % 60)).padStart(2, "0")}` : "";
  const meta = [p.author ? (p.kind === "book" ? `by ${esc(p.author)}` : p.kind === "video" || p.kind === "bookmark" ? esc(p.author) : `@${esc(p.author)}`) : "", dur,
                p.details.unavailable ? "unavailable on YouTube" : "", p.kind === "book" ? esc(p.details.year || "") : date,
                p.details.likes != null ? `${fmt(p.details.likes)} likes` : "", p.details.pages ? `${p.details.pages} pages` : ""].filter(Boolean).join(" · ");
  d.innerHTML = `
  <div class="grid h-full grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] max-md:grid-cols-1 max-md:grid-rows-[auto_minmax(0,1fr)]">
    <div class="stage relative flex min-h-0 items-center justify-center overflow-hidden max-md:h-[42dvh] ${p.kind === "book" ? "bg-raised p-8 max-md:p-4" : "bg-black"}">${stage()}</div>
    <div class="flex min-h-0 flex-col">
      <div class="flex items-center gap-1 border-b border-line px-4 py-2">
        <span class="inline-flex items-center gap-2 text-sm text-fg2">${dot(plat.color)}${plat.name}</span>
        <span class="ml-2 font-mono text-xs text-fg3 tabular-nums">${pos + 1} of ${fmt(list.length)}</span>
        <span class="ml-auto"></span>
        <button class="icon-btn" data-go="-1" title="Previous (←)" aria-label="Previous item">${icon("chevron-left")}</button>
        <button class="icon-btn" data-go="1" title="Next (→)" aria-label="Next item">${icon("chevron-right")}</button>
        <a class="icon-btn" href="${esc(p.url)}" target="_blank" rel="noopener" title="Open on ${plat.name}" aria-label="Open on ${plat.name}">${icon("external-link")}</a>
        <button class="icon-btn" data-close title="Close (Esc)" aria-label="Close">${icon("x")}</button>
      </div>
      <div class="min-h-0 overflow-y-auto px-5 py-4">
        ${p.removed ? `<p class="mb-3 inline-flex items-center gap-2 rounded-md bg-raised px-2 py-1 text-xs text-fg2">${icon("archive", 12)}No longer saved on ${plat.name}</p>` : ""}
        <h2 class="text-xl leading-snug font-medium text-fg">${esc(heading)}</h2>
        <p class="mt-1 text-sm text-fg2">${meta}</p>
        ${p.details.link ? `<a href="${esc(p.details.link)}" target="_blank" rel="noopener" class="mt-1 inline-flex items-center gap-1 text-sm text-accent underline-offset-2 hover:underline">${icon("link", 14)}${esc(p.details.domain || "Source")}</a>` : ""}
        ${p.kind === "book" && p.details.rating ? `<p class="mt-2 text-base">${stars(p.details.rating)}</p>` : ""}
        ${p.summary ? `<p class="mt-4 text-[15px] leading-relaxed text-fg">${esc(p.summary)}</p>` : ""}
        ${p.topics.length ? `<div class="mt-4 flex flex-wrap gap-2">${p.topics.map(t => `<button class="chip" data-topic="${esc(t)}" title="Show everything about ${esc(t)}">${icon("tag", 12)}${esc(t)}</button>`).join("")}</div>` : ""}
        ${cols.length ? `<p class="mt-3 text-sm text-fg2">In ${cols.map(esc).join(", ")}</p>` : ""}
        ${p.tags.length ? `<p class="mt-2 text-xs text-fg3">${p.tags.map(esc).join(" · ")}</p>` : ""}
        ${related.length ? `<div class="mt-5"><h3 class="text-sm text-fg2">Related</h3>
          <div class="mt-2 grid grid-cols-4 gap-2">${related.map(r => `<button data-related="${esc(r.id)}" class="group relative aspect-square overflow-hidden rounded-lg bg-raised" title="${esc(r.title || r.name || "")}" aria-label="Related: ${esc(r.title || r.name || r.kind)}">
            ${r.thumb ? `<img src="${r.thumb}" alt="" loading="lazy" class="size-full object-cover transition-transform duration-300 ease-out group-hover:scale-[1.03]">` : `<span class="flex size-full items-center justify-center p-1 text-center text-xs text-fg2">${esc(r.title || r.name || "")}</span>`}
            <span class="absolute bottom-1.5 left-1.5 size-2 rounded-full ring-2 ring-black/30" style="background:${PLATFORMS[r.source]?.color}"></span></button>`).join("")}</div></div>` : ""}
        <div class="mt-4">
          ${p.kind === "book" ? section("My review", p.details.review, true) : section(p.kind === "post" ? "Caption" : "Description", p.text, !p.summary)}
          ${p.details.chapters ? section("Chapters", p.details.chapters.join("\n")) : ""}
          ${section("What's said", p.transcript, true)}
          ${section("Text on screen", p.ocr)}
        </div>
      </div>
    </div>
  </div>`;
  const st = d.querySelector(".stage");
  st.addEventListener("click", e => {
    const b = e.target.closest(".slide"); if (!b) return;
    i = (i + +b.dataset.step + p.media.length) % p.media.length; st.innerHTML = stage();
  });
  if (!d.open) d.showModal();
}
function step(n) {
  const list = visible(), pos = list.findIndex(x => x.id === current);
  if (pos >= 0 && list.length) openItem(list[(pos + n + list.length) % list.length].id);
}
$("#dlg").addEventListener("click", e => {
  if (e.target === $("#dlg") || e.target.closest("[data-close]")) return $("#dlg").close();
  const go = e.target.closest("[data-go]"); if (go) return step(+go.dataset.go);
  const rel = e.target.closest("[data-related]"); if (rel) return openItem(rel.dataset.related);
  const t = e.target.closest("[data-topic]");
  if (t) { $("#dlg").close(); S.topic = t.dataset.topic; S.cluster = null; writeURL(); renderSide(); render(); }
});
$("#dlg").addEventListener("close", () => { $("#dlg").innerHTML = ""; current = null; });  // stops video playback

// ---------- filters drawer (phones: the sidebar slides in) ----------
function drawer(open) {
  $("#sidebar").toggleAttribute("data-open", open);
  $("#scrim").classList.toggle("hidden", !open);
  $("#filtersBtn").setAttribute("aria-expanded", open);
}
$("#filtersBtn").addEventListener("click", () => drawer(true));
$("#sideDone").addEventListener("click", () => drawer(false));
$("#scrim").addEventListener("click", () => drawer(false));

// ---------- update ----------
let polling = null;
function ago(ts) {
  const m = Math.round((Date.now() / 1000 - ts) / 60);
  return m < 60 ? `${m} min ago` : m < 48 * 60 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`;
}
async function refreshUpdate(open) {
  const u = await (await fetch("/api/update")).json();
  const p = $("#updatePanel");
  $("#settingsBtn").hidden = u.read_only;
  $("#updateLabel").textContent = u.read_only ? "Synced" : u.running ? "Updating" : "Update";
  $("#updateIcon").firstChild?.classList.toggle("animate-spin", u.running);
  const rows = u.sources.map(s => `<li class="flex items-start gap-3 py-2">
      <span class="mt-0.5 text-fg3">${icon(PLATFORMS[s.source]?.icon || "circle")}</span>
      <div class="min-w-0 flex-1"><div class="flex items-center text-sm text-fg">${PLATFORMS[s.source]?.name || s.source}<span class="ml-auto font-mono text-xs text-fg3 tabular-nums">${fmt(s.count)}</span></div>
      <div class="text-xs text-fg2">${s.last ? "Last sync " + ago(s.last) : "Never synced"}${s.allowed ? "" : `. ${esc(s.reason)}`}</div></div></li>`).join("");
  const log = u.log.length && (u.running || u.exit !== null) ? `<pre class="mt-3 max-h-40 overflow-auto rounded-lg bg-raised p-2 font-mono text-[11px] leading-4 whitespace-pre-wrap text-fg2">${esc(u.log.join("\n"))}</pre>` : "";
  const result = !u.running && u.exit !== null ? `<p class="mt-2 text-xs ${u.exit === 0 ? "text-fg2" : "text-[#dc2626]"}">${u.exit === 0 ? "Finished. New items are in." : "The update stopped with an error; the log above says why."}</p>` : "";
  p.innerHTML = `<h3 class="text-sm font-medium">${u.read_only ? "Read-only copy" : "Update your library"}</h3>
    <p class="mt-1 text-xs text-fg2">${u.read_only ? "Kept up to date by the machine that syncs your platforms. New saves show up after its next update."
      : "Fetches only new saves, then downloads and processes them. Platforms with a login are limited to protect your account."}</p>
    ${u.sources.length ? `<ul class="mt-2 divide-y divide-line">${rows}</ul>` : `<p class="mt-3 text-sm text-fg2">No platform enabled yet: edit <code class="font-mono">data/config.toml</code>.</p>`}
    ${log}${result}
    <div class="mt-3 flex justify-end gap-2"><button class="btn" data-panel-close>Close</button>
    ${u.read_only ? "" : `<button class="btn-primary" id="startUpdate" ${u.running || !u.sources.length ? "disabled" : ""}>${u.running ? "Running…" : "Update now"}</button>`}</div>`;
  if (open) p.classList.remove("hidden");
  if (u.running && !polling) polling = setInterval(() => refreshUpdate(false), 2000);
  if (!u.running && polling) { clearInterval(polling); polling = null; await load(); renderSide(); render(); }
}
$("#updateBtn").addEventListener("click", () => {
  const p = $("#updatePanel"), open = p.classList.contains("hidden");
  $("#updateBtn").setAttribute("aria-expanded", open);
  if (open) refreshUpdate(true); else p.classList.add("hidden");
});
$("#updatePanel").addEventListener("click", async e => {
  if (e.target.closest("[data-panel-close]")) { $("#updatePanel").classList.add("hidden"); $("#updateBtn").setAttribute("aria-expanded", false); }
  if (e.target.closest("#startUpdate")) { await fetch("/api/update", { method: "POST" }); refreshUpdate(true); }
});

// ---------- controls ----------
function clearFilter(f) {
  if (f === "all") { S.platform = S.topic = S.col = S.cluster = null; S.removed = false; S.q = ""; S.results = null; $("#q").value = ""; }
  else if (f === "q") { S.q = ""; S.results = null; $("#q").value = ""; }
  else S[f] = f === "removed" ? false : null;
}
document.addEventListener("click", e => {
  const c = e.target.closest("[data-clear]");
  if (c) { clearFilter(c.dataset.clear); writeURL(); renderSide(); render(); }
});
$("#side").addEventListener("click", e => {
  if (e.target.closest("[data-more]")) { S.allTopics = !S.allTopics; renderSide(); return; }
  const b = e.target.closest("[data-f]"); if (!b) return;
  const f = b.dataset.f, v = b.dataset.v;
  if (f === "removed") S.removed = !S.removed;
  else if (f === "cluster") S.cluster = S.cluster === +v ? null : +v;
  else S[f] = !v || S[f] === v ? null : v;
  writeURL(); renderSide(); render();
});
document.querySelector("[role=tablist]").addEventListener("click", e => {
  const t = e.target.closest("[data-tab]"); if (!t) return;
  S.tab = t.dataset.tab; writeURL(); render();
});
$("#mode").addEventListener("change", () => { S.mode = $("#mode").value; S.cluster = null; V.x = V.y = 0; V.k = 1; writeURL(); renderSide(); render(); });
document.addEventListener("click", e => { if (e.target.closest("#resetFilters")) resetView(); });
$("#grid").addEventListener("click", e => { const b = e.target.closest("[data-id]"); if (b) openItem(b.dataset.id); });
$("#surprise").addEventListener("click", () => { const l = visible(); if (l.length) openItem(l[Math.floor(Math.random() * l.length)].id); });
$("#home").addEventListener("click", e => { e.preventDefault(); clearFilter("all"); S.tab = "grid"; writeURL(); renderSide(); render(); });

let qTimer, searchSeq = 0;
async function runSearch() {
  const q = S.q.trim(), seq = ++searchSeq;
  if (!q) { S.results = null; render(); return; }
  $("#status").textContent = "Searching…";
  const res = (await (await fetch("/api/search?k=120&q=" + encodeURIComponent(q))).json()).results;
  if (seq === searchSeq) { S.results = res; render(); }
}
$("#q").addEventListener("input", () => {
  clearTimeout(qTimer);
  qTimer = setTimeout(() => { S.q = $("#q").value; writeURL(false); runSearch(); }, 350);
});
addEventListener("keydown", e => {
  if ($("#settingsDlg").open) return;
  if ($("#dlg").open) {
    if (e.key === "ArrowRight") step(1);
    if (e.key === "ArrowLeft") step(-1);
    return;
  }
  if (e.target.matches("input, select, textarea")) { if (e.key === "Escape") e.target.blur(); return; }
  if (e.key === "Escape" && $("#sidebar").hasAttribute("data-open")) return drawer(false);
  if (e.key === "/") { e.preventDefault(); $("#q").focus(); }
  if (e.key === "g" || e.key === "m") { S.tab = e.key === "g" ? "grid" : "map"; writeURL(); render(); }
  if (S.tab === "map" && (e.key === "+" || e.key === "=")) zoomAt(1.5);
  if (S.tab === "map" && (e.key === "-" || e.key === "_")) zoomAt(1 / 1.5);
  if (S.tab === "map" && e.key === "0") resetView();
  if (e.key === "Escape") $("#updatePanel").classList.add("hidden");
});
addEventListener("popstate", () => { readURL(); $("#q").value = S.q; renderSide(); S.q ? runSearch() : (S.results = null, render()); });

// ---------- settings: form built from the pydantic JSON schema, saved to data/config.toml ----------
const SECTION = { sources: ["Platforms", "Which platforms to read and where from"], models: ["Models", "Where the AI steps run"],
                  guard: ["Limits", "Protect your accounts on platforms with a login"] };
const sentence = k => (k.charAt(0).toUpperCase() + k.slice(1)).replaceAll("_", " ").replace(/\bllm\b/i, "LLM").replace(/\burl\b/i, "URL").replace(/\bapi\b/i, "API").replace(/\bcsv\b/i, "CSV");
let settingsData = null;
function resolve(schema, node) { return node?.$ref ? schema.$defs[node.$ref.split("/").pop()] : node; }
function field(path, key, prop, value) {
  const id = "set-" + path.replaceAll(".", "-"), help = prop.description ? `<p class="mt-1 text-xs text-fg3">${esc(prop.description)}</p>` : "";
  const label = `<label for="${id}" class="text-sm text-fg">${sentence(key)}</label>`;
  if (prop.type === "boolean") return `<div class="flex items-start gap-3 py-2"><input id="${id}" data-path="${path}" data-type="bool" type="checkbox" ${value ? "checked" : ""} class="mt-0.5 size-4 accent-[var(--accent)]"><div>${label}${help}</div></div>`;
  let input;
  if (prop.enum) input = `<select id="${id}" data-path="${path}" class="h-8 w-full rounded-lg border border-line bg-raised px-2 text-sm">${prop.enum.map(o => `<option ${o === value ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  else if (prop.type === "integer" || prop.type === "number") input = `<input id="${id}" data-path="${path}" data-type="num" type="number" step="${prop.type === "integer" ? 1 : "any"}" ${prop.minimum != null ? `min="${prop.minimum}"` : ""} ${prop.maximum != null ? `max="${prop.maximum}"` : ""} value="${value}" class="h-8 w-32 rounded-lg border border-line bg-raised px-2 font-mono text-sm tabular-nums">`;
  else if (prop.type === "array") input = `<input id="${id}" data-path="${path}" data-type="list" value="${esc(value.join(", "))}" class="h-8 w-full rounded-lg border border-line bg-raised px-2 text-sm">`;
  else input = `<input id="${id}" data-path="${path}" value="${esc(value)}" spellcheck="false" class="h-8 w-full rounded-lg border border-line bg-raised px-2 font-mono text-[13px]">`;
  return `<div class="py-2">${label}<div class="mt-1">${input}</div>${help}</div>`;
}
function group(schema, node, values, path) {  // scalar fields of one model, then its sub-models as sub-groups
  const props = resolve(schema, node).properties, out = [], subs = [];
  for (const [k, prop] of Object.entries(props)) {
    const p = resolve(schema, prop);
    if (p.type === "object" || p.properties) subs.push([k, p]);
    else out.push(field(`${path}.${k}`, k, { ...p, description: prop.description || p.description }, values[k]));
  }
  for (const [k, p] of subs) {
    const plat = PLATFORMS[k];
    const title = plat ? `<span class="text-fg3">${icon(plat.icon)}</span>${plat.name}` : sentence(k === "llm" ? "LLM (titles, summaries, tags)" : k === "transcribe" ? "Transcription" : k);
    out.push(`<fieldset class="mt-3 rounded-xl border border-line px-4 py-2"><legend class="flex items-center gap-2 px-1 text-sm font-medium">${title}</legend>${group(schema, p, values[k], `${path}.${k}`)}</fieldset>`);
  }
  return out.join("");
}
async function openSettings() {
  settingsData = await (await fetch("/api/settings")).json();
  const { schema, config: cfg, topics } = settingsData, d = $("#settingsDlg");
  const tabs = [...Object.keys(SECTION), "topics"];
  d.innerHTML = `<form method="dialog" class="flex max-h-[90vh] flex-col">
    <div class="flex items-center border-b border-line px-5 py-3"><h2 class="text-base font-medium">Settings</h2>
      <button type="button" class="icon-btn ml-auto" data-close-settings aria-label="Close">${icon("x")}</button></div>
    <div class="flex gap-1 border-b border-line px-4 pt-2" role="tablist">${tabs.map((t, i) =>
      `<button type="button" role="tab" data-stab="${t}" aria-selected="${i === 0}" class="rounded-t-lg px-3 py-2 text-sm text-fg2 aria-selected:bg-raised aria-selected:text-fg">${t === "topics" ? "Topics" : SECTION[t][0]}</button>`).join("")}</div>
    <div id="settingsErr" class="hidden mx-5 mt-3 rounded-lg border border-[#dc2626]/40 px-3 py-2 text-sm text-[#dc2626]"></div>
    <div class="min-h-0 flex-1 overflow-y-auto px-5 py-3">
      ${Object.entries(SECTION).map(([k, [, sub]], i) => `<section data-spane="${k}" class="${i ? "hidden" : ""}"><p class="text-sm text-fg2">${sub}</p>${group(schema, schema.properties[k], cfg[k], k)}</section>`).join("")}
      <section data-spane="topics" class="hidden"><p class="text-sm text-fg2">Broad topics for the topic filter, one per line. Each item gets the 1–3 closest ones; the next update re-tags everything when this list changes.</p>
        <textarea id="topicsText" rows="16" spellcheck="false" class="mt-3 w-full rounded-lg border border-line bg-raised p-3 font-mono text-[13px] leading-6">${esc(topics.join("\n"))}</textarea></section>
    </div>
    <div class="flex items-center gap-2 border-t border-line px-5 py-3"><span class="truncate font-mono text-xs text-fg3">${esc(settingsData.path)}</span>
      <button type="button" class="btn ml-auto" data-close-settings>Cancel</button><button type="button" class="btn-primary" id="saveSettings">Save</button></div>
  </form>`;
  d.showModal();
}
async function saveSettings() {
  const cfg = structuredClone(settingsData.config);
  for (const el of $("#settingsDlg").querySelectorAll("[data-path]")) {
    const keys = el.dataset.path.split("."), last = keys.pop(), obj = keys.reduce((o, k) => o[k], cfg);
    obj[last] = el.dataset.type === "bool" ? el.checked : el.dataset.type === "num" ? Number(el.value)
      : el.dataset.type === "list" ? el.value.split(",").map(x => x.trim()).filter(Boolean) : el.value.trim();
  }
  const r = await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config: cfg, topics: $("#topicsText").value.split("\n") }) });
  const res = await r.json();
  if (!r.ok) {
    const err = $("#settingsErr");
    err.innerHTML = (Array.isArray(res.detail) ? res.detail : [String(res.detail)]).map(m => `<div>${esc(m)}</div>`).join("");
    err.classList.remove("hidden"); return;
  }
  $("#settingsDlg").close();
  toast(res.topics_changed ? "Saved. Topics are re-tagged on the next update." : "Saved. Changes apply from the next update.");
  refreshUpdate(false);
}
let toastTimer;
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add("hidden"), 3500);
}
$("#settingsBtn").addEventListener("click", openSettings);
$("#settingsDlg").addEventListener("click", e => {
  if (e.target === $("#settingsDlg") || e.target.closest("[data-close-settings]")) return $("#settingsDlg").close();
  const t = e.target.closest("[data-stab]");
  if (t) {
    $("#settingsDlg").querySelectorAll("[data-stab]").forEach(b => b.setAttribute("aria-selected", b === t));
    $("#settingsDlg").querySelectorAll("[data-spane]").forEach(p => p.classList.toggle("hidden", p.dataset.spane !== t.dataset.stab));
  }
  if (e.target.closest("#saveSettings")) saveSettings();
});

// ---------- theme: Auto (system) → Light → Dark ----------
const THEMES = { auto: ["monitor", "Auto (follows the system)"], light: ["sun", "Light"], dark: ["moon", "Dark"] };
function applyTheme(t) {
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  try { localStorage.setItem("theme", t); } catch {}
  const b = $("#themeBtn");
  b.innerHTML = icon(THEMES[t][0]); b.title = `Theme: ${THEMES[t][1]}`; b.setAttribute("aria-label", b.title);
  readTheme(); invalidate();
}
$("#themeBtn").addEventListener("click", () => {
  const order = Object.keys(THEMES), cur = document.documentElement.dataset.theme || "auto";
  applyTheme(order[(order.indexOf(cur) + 1) % order.length]);
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { readTheme(); invalidate(); });

(async () => {
  paintIcons();
  applyTheme(document.documentElement.dataset.theme || "auto");
  readURL();
  $("#q").value = S.q;
  await load();
  renderSide();
  loadLayout();
  S.q ? runSearch() : render();
  refreshUpdate(false);
})();
