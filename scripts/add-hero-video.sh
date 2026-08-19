#!/usr/bin/env bash
# Fetch a hero clip and make it web-sized.
#
#   ./scripts/add-hero-video.sh "https://…/clip.mp4"
#
# Writes web/media/hero.webm and web/media/hero.mp4. The page offers both:
# Chrome and Firefox take the smaller WebM, Safari falls through to the mp4.
set -euo pipefail

URL="${1:-}"
if [ -z "$URL" ]; then
  echo "usage: $0 <url-or-path-of-clip>" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/web/media"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$OUT"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg not found. Install it first:" >&2
  echo "  macOS    brew install ffmpeg" >&2
  echo "  Ubuntu   sudo apt install ffmpeg" >&2
  exit 1
fi

echo "→ fetching"
if [ -f "$URL" ]; then
  cp "$URL" "$TMP/src.mp4"
else
  curl -fsSL --retry 3 -o "$TMP/src.mp4" "$URL"
fi

# 1600px wide is plenty behind text, and the audio track is dead weight since
# the element is muted. faststart puts the index first so playback can begin
# before the whole file has arrived.
echo "→ encoding mp4 (this takes a minute)"
ffmpeg -loglevel error -y -i "$TMP/src.mp4" \
  -an -vf "scale=1600:-2:flags=lanczos" \
  -c:v libx264 -profile:v high -pix_fmt yuv420p \
  -crf 31 -preset slow -movflags +faststart \
  "$OUT/hero.mp4"

echo "→ encoding webm"
ffmpeg -loglevel error -y -i "$TMP/src.mp4" \
  -an -vf "scale=1600:-2:flags=lanczos" \
  -c:v libvpx-vp9 -pix_fmt yuv420p -b:v 0 -crf 40 -row-mt 1 \
  "$OUT/hero.webm"

echo "✓ web/media/hero.mp4  ($(du -h "$OUT/hero.mp4" | cut -f1))"
echo "✓ web/media/hero.webm ($(du -h "$OUT/hero.webm" | cut -f1))"
SIZE=$(du -h "$OUT/hero.mp4" | cut -f1)
[ "${SIZE%M*}" -gt 3 ] 2>/dev/null && \
  echo "! over the 3 MB budget — re-run with a higher -crf if you want it smaller" || true
