#!/usr/bin/env python
"""Transcribe an audio/video file into English, producing:

  <base>.en.srt / .en.vtt / .en.txt   -- English reference subtitles + transcript
  <base>.sentences.json               -- [{id,start,end,en}] units for translation

It uses the faster-whisper engine with WORD-LEVEL timestamps, then groups words into
short units by punctuation, speech pauses, and a hard duration cap. Word-level
timing is what lets the Korean translation stay in sync even though Korean and
English word order differ -- see SKILL.md.

Usage:
  python transcribe.py AUDIO OUT_DIR BASE [MODEL_SIZE] [LANGUAGE] [TASK]
    MODEL_SIZE default: small.en
        English-only:  tiny.en / base.en / small.en / medium.en
        Multilingual:  tiny / base / small / medium / large-v3
        A `.en` model can ONLY hear English. Fed another language it silently
        emits English words that merely sound alike, so the output is fluent
        nonsense. Non-English audio needs a multilingual model.
    LANGUAGE   default: en   (ISO code, e.g. hi/ja/es; "auto" to detect)
    TASK       default: transcribe
        transcribe -> write down what is said, in LANGUAGE
        translate  -> write it down translated into English (any source
                      language). Requires a multilingual model.
"""
import json
import os
import re
import sys

# faster-whisper's default xet download backend can 401 on some hosts; the
# classic HF download path is reliable, so disable xet before importing.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
from faster_whisper import WhisperModel  # noqa: E402

PAUSE = 0.6    # gap between words (s) that forces a unit boundary
MAXDUR = 7.0   # hard cap on unit length (s) so punctuation-less ASR can't blob


def group_units(words):
    units, cur, start = [], [], None
    n = len(words)
    for i, (word, ws, we) in enumerate(words):
        if start is None:
            start = ws
        cur.append(word)
        gap = (words[i + 1][1] - we) if i + 1 < n else 999
        end_punct = bool(re.search(r"[.!?]\"?$", word.strip()))
        if end_punct or gap > PAUSE or (we - start) > MAXDUR:
            units.append({"start": round(start, 3), "end": round(we, 3),
                          "en": "".join(cur).strip()})
            cur, start = [], None
    if cur:
        units.append({"start": round(start, 3), "end": round(words[-1][2], 3),
                      "en": "".join(cur).strip()})
    for i, u in enumerate(units, 1):
        u["id"] = i
    return units


def fmt(sec, sep):
    total = int(sec)
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    ms = int(round((sec - total) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def write_subs(units, out_dir, base):
    srt, vtt = [], ["WEBVTT", ""]
    for i, u in enumerate(units, 1):
        end = u["end"] if u["end"] > u["start"] else u["start"] + 1.0
        srt.append(f"{i}\n{fmt(u['start'], ',')} --> {fmt(end, ',')}\n{u['en']}\n")
        vtt.append(f"{i}\n{fmt(u['start'], '.')} --> {fmt(end, '.')}\n{u['en']}\n")
    open(os.path.join(out_dir, f"{base}.en.srt"), "w", encoding="utf-8").write("\n".join(srt))
    open(os.path.join(out_dir, f"{base}.en.vtt"), "w", encoding="utf-8").write("\n".join(vtt))
    txt = " ".join(u["en"] for u in units)
    open(os.path.join(out_dir, f"{base}.en.txt"), "w", encoding="utf-8").write(txt + "\n")


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    audio, out_dir, base = sys.argv[1:4]
    model_size = sys.argv[4] if len(sys.argv) > 4 else "small.en"
    language = sys.argv[5] if len(sys.argv) > 5 else "en"
    task = sys.argv[6] if len(sys.argv) > 6 else "transcribe"
    if language in ("auto", "none", ""):
        language = None
    if task == "translate" and model_size.endswith(".en"):
        sys.exit("translate needs a multilingual model; drop the .en suffix "
                 f"(got {model_size!r})")
    os.makedirs(out_dir, exist_ok=True)

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio, language=language, task=task,
                                   word_timestamps=True, vad_filter=False)

    words = []
    for seg in segments:
        for w in (seg.words or []):
            words.append((w.word, w.start, w.end))
    if not words:
        sys.exit("No speech recognized.")

    units = group_units(words)
    with open(os.path.join(out_dir, f"{base}.sentences.json"), "w", encoding="utf-8") as f:
        json.dump(units, f, ensure_ascii=False, indent=2)
    write_subs(units, out_dir, base)

    print(f"OK: {len(units)} units, {words[-1][2]:.1f}s")
    print(f"  -> {base}.en.srt / .en.vtt / .en.txt")
    print(f"  -> {base}.sentences.json  (translate this)")


if __name__ == "__main__":
    main()
