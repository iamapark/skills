#!/usr/bin/env bash
# One-time environment setup for the youtube-subtitle skill.
# Creates a dedicated Python venv with only what the skill uses:
#   faster-whisper  speech recognition (CTranslate2, no PyTorch needed)
#   yt-dlp          YouTube download (the [default] extra adds the JS challenge solver)
# Safe to re-run: it no-ops if both are already installed.
set -euo pipefail

VENV="${YKS_VENV:-$HOME/.cache/youtube-subtitle/venv}"
LOCAL_FILE=0
case "${1:-}" in
  --local-file) LOCAL_FILE=1 ;;
  "") ;;
  *) printf 'Usage: %s [--local-file]\n' "$0" >&2; exit 1 ;;
esac
[ "$#" -le 1 ] || { printf 'Too many arguments\n' >&2; exit 1; }

log() { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[setup:error]\033[0m %s\n' "$*" >&2; exit 1; }

# --- system deps -----------------------------------------------------------
command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg not found. Install it (macOS: 'brew install ffmpeg')."

# --- locate python >= 3.10 (yt-dlp's minimum) -----------------------------
PY=""
for c in python3.12 python3.13 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 \
     && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  if command -v brew >/dev/null 2>&1; then
    log "no python >= 3.10 found; installing python@3.12 via homebrew..."
    brew install python@3.12
    PY="$(brew --prefix)/bin/python3.12"
  else
    die "python >= 3.10 not found and homebrew unavailable. Install Python 3.10+ manually."
  fi
fi
log "using python: $PY"

# YouTube needs an external JS runtime; local media does not.
if [ "$LOCAL_FILE" -eq 0 ]; then
  "$PY" - <<'PY' || die "YouTube downloads need Deno 2.3+ or Node.js 22+ on PATH (macOS: brew install deno). For local media use --local-file."
import re
import subprocess
import sys

for command, minimum in (("deno", (2, 3, 0)), ("node", (22, 0, 0))):
    try:
        output = subprocess.check_output([command, "--version"], text=True,
                                         stderr=subprocess.DEVNULL, timeout=5)
        version = re.search(r"(?:^|\s)v?(\d+)\.(\d+)\.(\d+)", output)
        if version and tuple(map(int, version.groups())) >= minimum:
            sys.exit(0)
    except (OSError, subprocess.SubprocessError):
        pass
sys.exit(1)
PY
fi

if [ -x "$VENV/bin/python" ]; then
  "$VENV/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || die "Existing venv requires Python 3.10+. Set YKS_VENV to a new directory and rerun setup."
fi

# --- create venv + install -------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  log "creating venv at $VENV"
  mkdir -p "$(dirname "$VENV")"
  "$PY" -m venv "$VENV"
fi

if "$VENV/bin/python" -c "import faster_whisper, yt_dlp, yt_dlp_ejs" >/dev/null 2>&1 && [ -x "$VENV/bin/yt-dlp" ]; then
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
