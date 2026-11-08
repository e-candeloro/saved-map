# README demo

`docs/demo.gif` and `docs/demo.mp4` are made from real screen recordings of the app, composed with
[HyperFrames](https://hyperframes.heygen.com) (HTML rendered to video).

1. Run the app (`uv run savedmap serve`), then record the four takes headless at 1920×1080:
   `uv run python docs/demo-video/record_take.py <library|topic|map|search> <out_dir>`.
   To keep private topics out of the video, list them in `docs/demo-video/hide.json` (gitignored), e.g.
   `{"topics": ["health"], "collections": "diary|private", "words": "health|diary"}`: the recorder filters the API
   responses of its own browser session; your data is not changed.
2. Trim each take from the printed `start`, convert to H.264 (`ffmpeg -ss <start> -i take.webm -c:v libx264 -crf 18 -r 30 -an`)
   into `docs/demo-video/assets/<take>.mp4` (gitignored).
3. `cd docs/demo-video && npx hyperframes check && npx hyperframes render -o renders/demo.mp4 --video-frame-format=png`.
4. GIF: `ffmpeg -i renders/demo.mp4 -vf "fps=8,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" ../demo.gif`.

`SPEC.md` holds the numbers (look, timing, shots), `STORYLINES.md` the options considered, `REVIEW.md` what the review fixed.
