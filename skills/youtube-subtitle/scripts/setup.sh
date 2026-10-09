#!/usr/bin/env bash
# One-time environment setup for the youtube-subtitle skill.
# Creates a dedicated Python 3.12 venv (buzz-captions requires >=3.12,<3.13)
# and installs buzz-captions (which bundles faster-whisper + yt-dlp).
# Safe to re-run: it no-ops if the venv already has buzz installed.
set -euo pipefail

VENV="${YKS_VENV:-$HOME/.cache/youtube-subtitle/venv}"

log() { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[setup:error]\033[0m %s\n' "$*" >&2; exit 1; }

# --- system deps -----------------------------------------------------------
command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg not found. Install it (macOS: 'brew install ffmpeg')."

# --- locate python 3.12 ----------------------------------------------------
PY312=""
for c in python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
  if command -v "$c" >/dev/null 2>&1; then PY312="$(command -v "$c")"; break; fi
done
if [ -z "$PY312" ]; then
  if command -v brew >/dev/null 2>&1; then
    log "python3.12 not found; installing via homebrew..."
    brew install python@3.12
    PY312="$(brew --prefix)/bin/python3.12"
  else
    die "python3.12 not found and homebrew unavailable. Install Python 3.12 manually."
  fi
fi
log "using python: $PY312"

# --- create venv + install -------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  log "creating venv at $VENV"
  mkdir -p "$(dirname "$VENV")"
  "$PY312" -m venv "$VENV"
fi

if "$VENV/bin/python" -c "import buzz" >/dev/null 2>&1; then
  log "buzz-captions already installed."
else
  log "installing buzz-captions (large: torch + whisper, first run takes a few minutes)..."
  "$VENV/bin/pip" install --upgrade pip -q
  "$VENV/bin/pip" install "buzz-captions" -q
fi

log "ready. venv python: $VENV/bin/python"
echo "$VENV/bin/python"
