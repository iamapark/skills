#!/usr/bin/env bash
# One-time environment setup for the youtube-subtitle skill.
# Creates a dedicated Python venv with only what the skill uses:
#   faster-whisper  speech recognition (CTranslate2, no PyTorch needed)
#   yt-dlp          YouTube download (the [default] extra adds the JS challenge solver)
# Safe to re-run: it no-ops if both are already installed.
set -euo pipefail

VENV="${YKS_VENV:-$HOME/.cache/youtube-subtitle/venv}"

log() { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[setup:error]\033[0m %s\n' "$*" >&2; exit 1; }

# --- system deps -----------------------------------------------------------
command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg not found. Install it (macOS: 'brew install ffmpeg')."

# --- locate python >= 3.9 (faster-whisper's minimum) -----------------------
PY=""
for c in python3.12 python3.13 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 \
     && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  if command -v brew >/dev/null 2>&1; then
    log "no python >= 3.9 found; installing python@3.12 via homebrew..."
    brew install python@3.12
    PY="$(brew --prefix)/bin/python3.12"
  else
    die "python >= 3.9 not found and homebrew unavailable. Install Python 3.9+ manually."
  fi
fi
log "using python: $PY"

# --- create venv + install -------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  log "creating venv at $VENV"
  mkdir -p "$(dirname "$VENV")"
  "$PY" -m venv "$VENV"
fi

if "$VENV/bin/python" -c "import faster_whisper" >/dev/null 2>&1 && [ -x "$VENV/bin/yt-dlp" ]; then
  log "faster-whisper and yt-dlp already installed."
else
  log "installing faster-whisper and yt-dlp..."
  "$VENV/bin/pip" install --upgrade pip -q
  # av 19 dropped the `metadata_errors` argument that faster-whisper 1.2.x passes
  # to av.open(), so every transcription fails; stay on av 18 until that is fixed.
  "$VENV/bin/pip" install -q faster-whisper "av<19" "yt-dlp[default]"
fi

log "ready. venv python: $VENV/bin/python"
echo "$VENV/bin/python"
