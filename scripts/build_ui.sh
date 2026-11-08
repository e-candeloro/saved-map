#!/usr/bin/env bash
# Rebuild the UI's static CSS and icon subset after changing classes, tokens or icons in savedmap/static.
# Installs the official Tailwind npm packages once into ~/.cache/savedmap/ui-build and needs Node.
# Users of the app never run this: the outputs (app.css, icons.js) are committed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$HOME/.cache/savedmap/ui-build"
mkdir -p "$BUILD"
[ -x "$BUILD/node_modules/.bin/tailwindcss" ] || npm install --silent --prefix "$BUILD" tailwindcss@4.3.5 @tailwindcss/cli@4.3.5
# Tailwind resolves "tailwindcss" next to the input file, so compile a copy that lives in the build folder
sed "s#@source \"./#@source \"$ROOT/savedmap/static/#" "$ROOT/savedmap/static/app.src.css" > "$BUILD/app.src.css"
"$BUILD/node_modules/.bin/tailwindcss" -i "$BUILD/app.src.css" -o "$ROOT/savedmap/static/app.css" --minify
node "$ROOT/scripts/build_icons.mjs"
