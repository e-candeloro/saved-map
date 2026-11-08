GOAL:    a developer skimming the README understands in ~35 s that SavedMap pulls their saves from four
         platforms into one local library with topics, related items, a map and meaning search.
OUTPUT:  HyperFrames, 1920 x 1080, 30 fps; delivered as MP4 (1080p) and GIF (960 px, 8 fps)
TIME:    38 s x 30 = 1140 frames; no music (GIF)
LOOK:    ground #e8e7e4 flat; ink #171717; secondary #525252; one accent #c2410c (ember, the app's own)
         on one word per caption; display Inter 700 56 px, tracking -1%; sub Inter 400 28 px; mono
         JetBrains Mono 26 px for the command. Medium: product UI. The window: 1536 x 864 at (192, 168),
         radius 14, 1 px rgba(0,0,0,.08) border, shadow 0 24 px 60 px rgba(0,0,0,.16). No fake chrome.
OBJECTS: the app window (real recordings only), the SavedMap mark (2 x 2 rounded squares, one ember)
MOTION:  enter power3.out 0.6 s; caption swap: old line exits up 16 px + fade 0.25 s, new wipes in
         left→right (clip-path) 0.45 s, 0.1 s stagger to the sub; take changes: 0.3 s crossfade inside the
         window; camera: none (the recordings carry the motion)
SHOTS:   0–3.0 intro: mark, "Everything you saved." then "In one place you own." (accent: you own)
         3.0–10.2 library take x1.2: "Every platform, one library"
         10.2–18.3 topic take x1.15: "Topics across platforms" (+ Related)
         18.3–27.4 map take x1.1: "A map of your taste"
         27.4–34.7 search take x1.2: "Search by meaning"
         34.7–38 end card: mark + SavedMap, "Runs 100% on your machine · open source · MIT", `uv run savedmap serve`
BANNED:  dark void; glow; gradients; cream paper + serif; pill chips; centred everything; title over a
         dimmed screenshot; logo docked in a corner; text moving while read; fake browser chrome
QA:      t=1.5 headline readable; t=6, 14, 22, 31 caption + window, no overlap with the window; t=36.5 end card
