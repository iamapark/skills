---
name: youtube-subtitle
description: >-
  Generate timing-synced Korean subtitles (SRT/VTT) for a YouTube video by
  transcribing its audio locally with Buzz (the Whisper engine) and translating
  the English transcript into natural Korean with the LLM, then reviewing it
  with Jev before assembly. Only triggers when
  EXPLICITLY invoked via /youtube-subtitle (or when the user names this
  skill directly). Do NOT auto-trigger on generic transcription, translation, or
  subtitle requests — this skill is opt-in only.
---

# YouTube → Korean Subtitle

Produce a natural, well-timed **Korean** subtitle file for a YouTube video. The
pipeline is: download audio → transcribe English locally with Buzz's Whisper
engine → **you (the LLM) translate** the English transcript into Korean →
**Jev review + your targeted re-review** → build Korean SRT/VTT with original timings.

The translation step is the heart of this skill and is done by you, not a
machine-translation API — that is what makes the result read like a human
subtitler wrote it. Scripts handle transcription, timing, file assembly, and Jev
review requests. Jev flags possible problems; you decide how to revise the text.

## When to run

Only when the user explicitly invokes `/youtube-subtitle` or clearly asks
*this* skill to run. Do not activate it just because a message mentions
"subtitle" or "translate".

## Inputs you need

- A **YouTube URL** (or a local audio/video file path).
- Optional: output directory (default: `./yt-subs/<video title>/`), and Whisper
  model size (default `small.en`; a larger model buys accuracy at the cost of
  speed — see step 3 for choosing one).

When generating subtitles, if the URL is missing, ask for it before starting.
Inspecting or modifying this skill does not require a video URL.

## Prerequisites

- `ffmpeg` and a YouTube downloader (`yt-dlp`, installed with buzz-captions).
- A Python 3.12 venv with `buzz-captions`. The setup script builds it once and
  reuses it. `buzz-captions` requires Python `>=3.12,<3.13` specifically.
- `TYPESAFE_API_KEY` for Jev review. Before a full run, follow
  [Jev review and key setup](references/jev-review.md). Use the macOS Keychain or
  a private terminal prompt; never ask the user to paste a key into the conversation.
  Dry-run preparation works without a key, but is not completed review.

## Workflow

Work inside a per-video output directory so files don't collide. **Name the
folder after the video's title**, not its id — a human browsing `yt-subs/` should
be able to tell what each folder holds at a glance. Step 2 derives the folder
from the title automatically. All scripts live in this skill's `scripts/`
directory — reference them by absolute path. Claude Code replaces
`${CLAUDE_SKILL_DIR}` with this skill's directory when the skill loads, so the
line below works wherever the skill is installed (plugin, `~/.claude/skills/`
or a project's `.claude/skills/`). The `:-` default only applies if the variable
was not substituted, for example in an agent that lacks it:

```bash
SKILL_DIR="${CLAUDE_SKILL_DIR:-$HOME/.claude/skills/youtube-subtitle}"
```

Substitute `$SKILL_DIR` for `<SKILL_DIR>` in the commands below.

### 1. Set up the environment (once)

```bash
bash "<SKILL_DIR>/scripts/setup.sh"
```

It prints the venv Python path on the last line. Capture it:

```bash
VENV="$HOME/.cache/youtube-subtitle/venv"
PY="$VENV/bin/python"
```

The first run installs torch + Whisper and takes a few minutes; later runs are
instant. Run it in the background and wait, rather than blocking the UI.

### 2. Download the video

```bash
VIDEO="$("$VENV/bin/yt-dlp" \
  -f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b" \
  --merge-output-format mp4 -o "./yt-subs/%(title)s/%(title)s.%(ext)s" \
  --print after_move:filepath "<YOUTUBE_URL>" | tail -1)"
OUT="$(dirname "$VIDEO")"
BASE="$(basename "${VIDEO%.*}")"
echo "out:   $OUT"
echo "video: $VIDEO"
echo "base:  $BASE"
```

The output template uses the video's real title (`%(title)s`, sanitized by
yt-dlp into a filesystem-safe name) for **both the folder and the file** — so
you get `yt-subs/Some Real Talk Title/Some Real Talk Title.mp4`, not an opaque
`yt-subs/31GUkCBD-Uc/`. yt-dlp creates the intermediate directory itself, so
there is no `mkdir` to run and no id to look up. `--print after_move:filepath`
runs the real download (`after_move` is a post-download stage, so it does *not*
imply `--simulate`) and prints the exact absolute path saved, which is why `$OUT`
and `$BASE` are both derived from it rather than guessed.

**Every later step uses three variables derived here** — re-establish them in
each shell block (like `$PY`, they don't persist across calls): `$OUT` (the
per-video folder), `$VIDEO` (the full path) and `$BASE` (its filename stem, the
shared basename for all transcript/subtitle artifacts). If you run the download
in the background, read the task's last stdout line for `$VIDEO`, then recompute
`$OUT` and `$BASE` from it.

Downloading is a side-effecting action — expected here since the user asked for
subtitles for that video — but keep everything inside `$OUT`. A real title often
contains characters awkward on the ffmpeg command line (commas, quotes,
brackets), and now `$OUT` carries them too; that's fine — both are only ever
passed as plain quoted paths, and step 6's one picky consumer copies to a
safe-named temp file outside `$OUT`.

If a folder for that title already exists from an earlier run, reuse it (the
download is skipped) — but if it holds a *different* video that happens to share
a title, append the id (`-o "./yt-subs/%(title)s [%(id)s]/%(title)s.%(ext)s"`)
so the two don't overwrite each other.

### 3. Transcribe to English (Buzz / Whisper engine)

**Before transcribing the whole video, settle what language is actually
spoken.** The default model is English-only, and feeding it another language
does not fail loudly — it silently returns English words that merely *sound*
like what was said, so a 45-minute transcript can come back fluent and
completely meaningless. You only notice after paying for the full run.

Never decide from the title or the channel: an English title, English slides
and English technical terms all coexist happily with a lecture delivered in
Hindi, Tamil or Spanish. Cut a 2-minute clip from the middle (where the speaker
is explaining, not reading a title card) and transcribe just that:

```bash
PROBE="$(mktemp -d)"
ffmpeg -y -loglevel error -ss <mid> -t 120 -i "$VIDEO" -vn -ac 1 -ar 16000 "$PROBE/clip.wav"
"$PY" "<SKILL_DIR>/scripts/transcribe.py" "$PROBE/clip.wav" "$PROBE" probe small.en en
cat "$PROBE/probe.en.txt"
```

Read that text. Coherent English sentences → the default path is fine. Word
salad, or plausible-looking English that says nothing (`"Kowjaiga two K equal to
print numbers"`, `"Carjangi return"`) → the audio is not English. A 2-minute
probe costs well under a minute; a wrong full run costs the whole video twice.

**Then pick the model and task:**

| Audio | Model | Language | Task |
|-------|-------|----------|------|
| English | `small.en` / `medium.en` | `en` | `transcribe` |
| Anything else (incl. code-switched "Hinglish") | `small` / `medium` / `large-v3` — **no `.en`** | source code (`hi`, `ja`, …) or `auto` | `translate` |

```bash
# English
"$PY" "<SKILL_DIR>/scripts/transcribe.py" "$VIDEO" "$OUT" "$BASE" small.en en

# Non-English — multilingual model, Whisper translates to English for you
"$PY" "<SKILL_DIR>/scripts/transcribe.py" "$VIDEO" "$OUT" "$BASE" medium hi translate
```

A multilingual model is a separate ~1.4GB download (`medium`) even when the
same-size `.en` model is already cached; the probe run fetches it, so the probe
takes a few minutes the first time.

Why route non-English through `translate` rather than transcribing in the source
language: this skill's translation step (step 4) is yours, and English is the
bridge you translate from most reliably. It also keeps code-switched lectures
intact — Hindi narration and English identifiers (`printNums`, `cout`) come out
as one coherent English sentence instead of two half-transcribed languages.

**Model size, independently of language.** Larger models are ~3× slower per
step up. Prefer `medium`-class for lectures with dense jargon, accented
delivery, whiteboard math read aloud, or poor audio; `small` is enough for short
clips of clear, everyday speech. When unsure, reuse the same 2-minute probe to
compare two settings before committing to the full run.

This writes `$BASE.en.srt`, `$BASE.en.vtt`, `$BASE.en.txt`, and — crucially —
`$BASE.sentences.json`, a list of short units each with `{id, start, end, en}` and
accurate word-derived timing. Transcription is CPU-bound; run it in the
background and wait for the `OK: N units` line.

> Alternative English-only path: `"$PY" -m buzz add --task transcribe
> --model-type fasterwhisper --model-size small.en -l en --srt --vtt --txt -d
> "$OUT" "<YOUTUBE_URL>"`. This is the literal Buzz CLI, but its segmentation is
> coarse (whole-paragraph cues) or word-level, so for **Korean** subtitles
> prefer `transcribe.py`, which segments into translation-friendly units.

### 4. Translate into Korean (this is your job)

Read `$BASE.sentences.json`. It is small — read the **whole** thing so you
understand the full context before translating. Then produce a `translations.json`
mapping every unit `id` (as a string) to its Korean text:

```json
{ "1": "…", "2": "…", "3": "…" }
```

Write it with the Write tool. Follow the guidelines below — they are what
separate a good subtitle from a robotic one.

#### Translation guidelines

- **Translate for meaning and flow, not word-for-word.** Use natural spoken
  Korean (`~요`/`~죠` register for a casual explainer video; match the speaker's
  tone). The goal is what a Korean viewer would comfortably read at a glance.
- **Units are often cut mid-sentence.** `transcribe.py` breaks on pauses and a
  7-second cap, so one English sentence may span units 20–21. Because Korean
  word order differs, translate the *sentence* mentally, then split the Korean
  across those unit ids at a natural phrase boundary so each unit still shows a
  coherent chunk and, read in order, they flow as one sentence. This is the
  single most important technique — do not translate each fragment in isolation.
- **Keep timing implications in mind.** A unit's Korean should be readable within
  its `end - start` window. Don't overstuff a 1.5s unit. If a unit is short,
  keep its Korean short.
- **Fix obvious ASR errors using context and domain knowledge.** Whisper
  mis-hears names, tools, and jargon. Correct them in the Korean (e.g. a
  garbled tool name → the tool clearly meant; "rating documentation" →
  "문서 작성"). When in doubt, prefer the reading that makes sense in context.
- **Handle proper nouns and technical terms deliberately.** Keep product/skill/
  file names, code identifiers, notation, and URLs in their original form
  (`teach 스킬`, `Mission.md`, `MCP`, `U R U' L'`, `aihero.com/skills`). For a
  key concept, gloss it once: `상태 유지형(stateful)`, `근접 발달 영역(zone of
  proximal development)`, `ADR(아키텍처 결정 기록)` — then use the Korean short
  form afterward. Never translate a literal filename or a code token.
- **Quotes / speech within the transcript** → use `"…"`; make sure the JSON stays
  valid (escape inner double quotes).
- Every unit id in `sentences.json` must appear in `translations.json`, or the
  build step will refuse to run and tell you which ids are missing.

### 4.5. Review translations with Jev

Read [Jev review and key setup](references/jev-review.md) for credential loading,
report details, tuning, and failure handling. Jev receives transcript/translation
text and optional glossary, not audio or video. It cannot verify the actual speech.

```bash
"$PY" "<SKILL_DIR>/scripts/review_subtitles.py" \
  "$OUT/$BASE.sentences.json" "$OUT/translations.json" "$OUT" "$BASE"
```

Inspect `$BASE.review.md` and `.review.json`. Exit 0 means completed without flags;
exit 2 means completed with review candidates; exit 1 means failed/incomplete.
Each HTTP attempt, including retries/failures, appends start/finish events to
`$BASE.jev-api.jsonl`. Earlier runs remain; the report identifies its run ID and
log path. The history excludes API keys and subtitle text.
`--dry-run` creates a separate `.review-plan.json` without a key or network call.
Do not treat a dry run or API failure as a passed review.

Re-check flagged windows together with adjacent cues: Korean word order can move
meaning between IDs. Correct genuine errors in `translations.json`, preserving
IDs/timing, and rerun review after edits. For ambiguous ASR, listen to the audio.
Limit automatic correction/review to two passes, then report unresolved concerns.
If flags are false positives or acceptable after your inspection, retain the text,
explain the retained flags in the final report, and use `--accept-review-flags`
in step 5. This is an editorial decision you can make; it does not require an
extra user approval. Jev is advisory, including when it reports no issues.

### 5. Build the Korean subtitle files

```bash
"$PY" "<SKILL_DIR>/scripts/build_srt.py" \
  "$OUT/$BASE.sentences.json" "$OUT/translations.json" "$OUT" "$BASE"
```

Produces `$BASE.ko.srt` and `$BASE.ko.vtt` — same basename as the video, so media
players auto-load them — timings preserved, long lines wrapped toward two
display lines. The builder requires a completed `$BASE.review.json` matching the
current input hashes and covering every cue. Retained review flags require
`--accept-review-flags`; failed, absent or stale reports cannot be bypassed.

### 6. Verify sync (recommended)

Burn a couple of frames so you can confirm the Korean actually lands on screen at
the right moment. The `subtitles=` filter treats `:` `,` `'` `[` `]` in its
argument as syntax, and a real title routinely contains them — **in the filename
*and* now in `$OUT` itself**. So copy the SRT to a safe-named file in a temp
directory and point the filter there; never at anything under `$OUT`. (A title
like `… Chopra, Uber` otherwise fails with `No such filter: 'Uber/_verify.ko.srt'`.)
Use `-copyts` — without it, an input `-ss` seek resets timestamps and the
subtitle filter always draws cue #1 (a common false alarm):

```bash
VDIR="$(mktemp -d)"; cp "$OUT/$BASE.ko.srt" "$VDIR/v.srt"
for t in 5 <mid> <late>; do
  ffmpeg -y -loglevel error -copyts -ss $t -i "$VIDEO" \
    -vf "subtitles=$VDIR/v.srt:force_style='FontName=Apple SD Gothic Neo,FontSize=22'" \
    -frames:v 1 "$VDIR/verify_${t}s.png"
done
```

`$VIDEO` as the `-i` input and `$VDIR/verify_*.png` as the output are safe
whatever they're named — only the `-vf` argument is parsed as filtergraph syntax,
and it sees just `$VDIR/v.srt`. Read the PNGs and check the caption matches the
spoken content at that time. `rm -rf "$VDIR"` afterward — writing them outside
`$OUT` also keeps the deliverable folder clean. Also sanity-check the SRT parses
with no overlaps.

### 7. Embed the subtitles into the video (only if asked)

The sidecar `.ko.srt` already auto-loads in IINA/VLC. Do this step only when the
user wants the Korean baked into the video file itself. Two ways, and the choice
matters — **default to muxing**:

**Mux a subtitle track (lossless, ~1 second).** Copies both streams untouched and
adds a Korean subtitle track flagged `default`, so players turn it on by
themselves. File grows by the size of the SRT (tens of KB):

```bash
ffmpeg -y -loglevel error -i "$VIDEO" -i "$OUT/$BASE.ko.srt" \
  -map 0:v -map 0:a -map 1 -c copy -c:s mov_text \
  -metadata:s:s:0 language=kor -disposition:s:0 default \
  -movflags +faststart "$OUT/$BASE.ko-softsub.mp4"
```

**Burn in (hardsub).** Pixels are rewritten, so the Korean shows anywhere — web
players, phones, previews, re-uploads — and can never be switched off. Costs a
full re-encode and a generation of quality loss, and the file gets much bigger
(a 316 kbps AV1 source became 2.6 Mbps H.264, 51 MB → 427 MB). Same filter-path
rule as step 6: `$OUT` contains the title, so the SRT must be copied to a
safe-named temp file first. Run it in the background — even with hardware
encoding it is roughly 3× realtime:

```bash
VDIR="$(mktemp -d)"; cp "$OUT/$BASE.ko.srt" "$VDIR/v.srt"
ffmpeg -y -loglevel warning -stats -i "$VIDEO" \
  -vf "subtitles=$VDIR/v.srt:force_style='FontName=Apple SD Gothic Neo,FontSize=20,Outline=2,Shadow=1,MarginV=28'" \
  -c:v h264_videotoolbox -b:v 2500k -c:a copy -movflags +faststart \
  "$OUT/$BASE.ko-hardsub.mp4"
```

`h264_videotoolbox` is the macOS hardware encoder; fall back to `-c:v libx264
-crf 20 -preset medium` if it isn't listed in `ffmpeg -encoders`. Verify a frame
straight out of the result — no `subtitles=` filter needed, the text is in the
picture now — then drop the temp dir:

```bash
ffmpeg -y -loglevel error -ss <mid> -i "$OUT/$BASE.ko-hardsub.mp4" \
  -frames:v 1 "$VDIR/burned.png"
rm -rf "$VDIR"
```

### 8. Report

Tell the user the final file paths (`$BASE.ko.srt`, `$BASE.ko.vtt`, inside the
title-named `$OUT` folder), the cue count, and the transcription model used.
Include the Jev review report path/status, returned model version, flagged cue
count, and any flags retained after inspection. Distinguish offline/mock tests
from a real API review; never imply the text review verified audio sync. Since the
subtitles share the video's basename, opening `$VIDEO` in IINA/VLC auto-loads
them (same folder, same name). Note that any unit can be tweaked by editing
`translations.json` and re-running steps 4.5–5 — and, if you ran step 7, that the
hardsub has to be re-encoded to pick those edits up while the sidecar and the
muxed track do not.

## Editing / re-running

`translations.json` and `$BASE.sentences.json` are the source of truth. To revise
specific lines, edit the Korean for those ids, rerun `review_subtitles.py`, then
`build_srt.py` (it rewrites `$BASE.ko.srt` / `.ko.vtt`) — no need to re-transcribe. To change
accuracy, re-run `transcribe.py` with a larger model (re-translation needed since
unit ids change).

## Notes & troubleshooting

- **Model download 401 / xet errors**: `transcribe.py` already sets
  `HF_HUB_DISABLE_XET=1` and reuses Buzz's model cache
  (`~/Library/Caches/Buzz/models`). If a fresh model still fails, run one
  `python -m buzz add …` (step 3 alternative) once to populate the cache.
- **Wrong Python**: buzz-captions installs only on Python 3.12. `setup.sh`
  locates or installs it via homebrew.
- **`.en` vs multilingual**: `small.en` and `small` are different downloads of
  the same size. `.en` models were trained on English only and cannot represent
  any other language — they do not report an error, they hallucinate
  English-sounding text. Verify the spoken language before a long run (step 3).
- **Translate task**: to make English→Korean, this skill translates *after*
  English transcription. (Whisper's own `translate` task only outputs English,
  so it cannot produce Korean directly — hence the LLM translation step.)
- ASR runs locally. The LLM handles translation in its configured environment;
  Jev review sends English/Korean text, cue metadata and the optional glossary
  to TypeSafe. The review scripts never upload audio/video. See
  [Jev review and key setup](references/jev-review.md) for API failures and keys.
