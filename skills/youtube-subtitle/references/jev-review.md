# Jev subtitle review

Run `scripts/review_subtitles.py` after translating and before assembling SRT/VTT.
This is an additional reviewer; the LLM still translates, checks the report and
decides how to revise. Jev never modifies the transcript, translations or timing.

## API key management

The script reads **only `TYPESAFE_API_KEY` from its environment**. It does not
accept keys in CLI arguments or load `.env` files. Never put a key in the skill,
`translations.json`, a report, a repository, or an agent conversation. No extra
Python dependencies are needed for the API client.

Recommended on macOS: use **Keychain Access** to create a new password item with:

- Keychain item name / service: `typesafe.ai`
- Account: `youtube-subtitle`
- Password: the API key

Use the Keychain Access UI to enter/update the secret so it does not enter shell
history or a command's argument list. In the terminal that runs review, load it:

```bash
export TYPESAFE_API_KEY="$(security find-generic-password \
  -s typesafe.ai -a youtube-subtitle -w)"
```

For a temporary session without Keychain, enter it privately in **zsh**:

```zsh
read -rs 'TYPESAFE_API_KEY?Jev API key: '
export TYPESAFE_API_KEY
```

Run these in the user's own terminal, without shell tracing (`set -x`). Do not
print the variable or run `security ... -w` by itself. An export in one terminal
does not change an already running Claude/Codex process: start the agent from
that terminal, or load from Keychain in the same shell invocation as the review
command. The OS may request Keychain access. Afterward, `unset TYPESAFE_API_KEY`.
To rotate, replace the stored password and revoke the old key in TypeSafe.

Audio/video stays local during this step. English text, Korean translations,
cue IDs/timings and the optional glossary go to `https://api.typesafe.ai` via HTTPS.
The key is only sent in the Authorization header; redirects are rejected.

## Running

With `PY`, `OUT`, `BASE`, and `SKILL_DIR` established as in SKILL.md:

```bash
"$PY" "$SKILL_DIR/scripts/review_subtitles.py" \
  "$OUT/$BASE.sentences.json" "$OUT/translations.json" "$OUT" "$BASE" \
  --dry-run
```

This performs local input checks and saves `$BASE.review-plan.json` / `.md`.
The JSON includes exact planned request bodies so they can be inspected without
an API key. No network call occurs, and the plan cannot authorize an SRT build.

After setting the key, omit `--dry-run` for a live review:

```bash
"$PY" "$SKILL_DIR/scripts/review_subtitles.py" \
  "$OUT/$BASE.sentences.json" "$OUT/translations.json" "$OUT" "$BASE"
```

Optional `--glossary "$OUT/glossary.json"` accepts an object such as
`{"stateful": "상태 유지형", "MCP": "MCP", "printNums": "printNums"}`.
Use `--model` to select an account-supported model; default is `jev-latest`.
The report records both the requested alias and each returned model version.

Exit codes:

| Code | Meaning | Next step |
|---|---|---|
| 0 | Review completed without flags, or dry run completed | Inspect status; a dry run is not a review |
| 2 | Review completed with candidates for re-review | Read the report and review those cues in context |
| 1 | Invalid input, key/access problem, API failure or incomplete review | Resolve the error and rerun; do not claim completion |

Do not chain review and build with unconditional `;` or ignore a nonzero exit.
Exit 2 is a useful report, not a service failure. Keep existing SRT/video outputs
marked as from the previous run if review/build fails; they are not newly verified.

## How to use the report

`$BASE.review.json` contains input SHA-256 hashes, per-window typed answers,
probability distributions, confidence, resolved model, latency and returned token
usage. `$BASE.review.md` lists local warnings and target cues to re-review.
On API failure the JSON is marked `failed`, with completed windows retained;
unprocessed windows have no verdict. A rerun currently calls **all** windows again
(there is no persistent response cache), so expect additional usage.

## API call history (JSONL)

Every real HTTP attempt appends to `$OUT/$BASE.jev-api.jsonl`. Re-running the same
video preserves earlier lines; the latest `.review.json` / `.md` is still replaced.
The report includes its `run_id` and absolute `api_log_path` so you can find the
matching history. No extra CLI option is needed.

Each attempt produces two JSON lines, `attempt_started` and `attempt_finished`.
Match them with `run_id`, `request_id` and `attempt`. A new run gets a new run ID;
retries retain the window's request ID and increment the attempt number.

- Start events: UTC start time, requested model, endpoint, window index, target
  cue IDs, request body SHA-256 and byte count.
- Finish events: UTC finish time, per-attempt elapsed seconds (excluding retry
  backoff), HTTP status when known, outcome, next retry delay, resolved model,
  returned token usage and validated categorical answers when available.
- Outcomes: `success`, `http_error`, `network_error`, `invalid_json`,
  `invalid_response`, or `interrupted`. Success means a valid API response, not
  proof that its subtitle judgments are correct. Missing usage is `null`, not zero.
  Well-formed returned usage is retained even if the answer contract is invalid.

Count `attempt_started` events to count attempts initiated by the client, and
`attempt_finished` events to examine known outcomes; do not count every line as
a separate request. Client attempts are not proof of receipt or billing by Jev.
A start without a finish can mean abrupt termination or a logging failure; its
remote outcome is unknown. HTTP retries are separate attempts. Requests failing
input/key checks and `--dry-run` perform no HTTP attempt and add no JSONL entries.

Logs omit the API key, Authorization headers, English/Korean text, glossary,
complete request/response bodies and upstream error text. Files use owner-only
permissions (`0600`), a writer lock, append mode and flush/fsync after each event.
If the start event cannot be written, the network request does not begin. If the
finish event cannot be written, review stops and the request may already have
been processed. Logs are not rotated automatically; archive them when needed.

To display only finished attempts without any API call:

```bash
"$PY" - "$OUT/$BASE.jev-api.jsonl" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as history:
    for line in history:
        event = json.loads(line)
        if event["event"] == "attempt_finished":
            print(event["finished_at"], event["run_id"], event["window_index"],
                  event["attempt"], event["outcome"], event["http_status"], event["usage"])
PY
```

## Reviewing the findings

Each request evaluates five independent questions: omission, addition, meaning
change, Korean flow and terminology. Windows aim for sentence ends after at least
three cues, capped at twelve, with two context cues on either side. Punctuation
is a heuristic; exceptionally long sentences can still span windows. Instructions
allow Korean meaning to move between adjacent cues and request `uncertain` when
context or ASR is inadequate. A flagged window identifies a range to inspect,
not a claim that every cue in it is wrong.

All `issue`/`uncertain` answers and `clear` answers below `--min-confidence`
(default 0.7) become review candidates. This is a provisional routing threshold,
not a measured probability of correctness. TypeSafe documents lower accuracy for
non-English/CJK text; assess Korean performance against the existing LLM reviewer.
No-flag results still need normal quality and audio/sync checks.

If an answer's `choice` is not its highest-probability option, the review does
not stop: that dimension is recorded as `uncertain` with `reported_choice` and
`inconsistent: true`, and the window becomes a review candidate. Jev returned
this for the same window on every rerun, so failing hard would block the build.

Local checks reject missing/extra/duplicate IDs, empty translations, multiline
translation values, invalid or overlapping times. They warn on more than
`--max-cps` (default 15, including spaces/punctuation) characters per second and
rendered lines longer than 24 characters. These are tunable workflow heuristics,
not a claim of universal Korean subtitle standards. Warnings do not change timing.

Re-check flagged windows and adjacent context. Fix real errors in
`translations.json`, then rerun review. If a warning is acceptable after actual
inspection, retain the wording and record why in your final report; do not rewrite
good subtitles merely to improve a score. For ASR ambiguity, listen to the relevant
audio rather than trusting a plausible reconstruction. Stop after at most two
automatic correction/review passes; surface unresolved issues instead of looping.

Build with the original command once review is complete:

```bash
"$PY" "$SKILL_DIR/scripts/build_srt.py" \
  "$OUT/$BASE.sentences.json" "$OUT/translations.json" "$OUT" "$BASE"
```

If flagged wording was inspected and intentionally retained, add
`--accept-review-flags`. This does not bypass missing, failed, dry-run or stale
reports. The builder checks hashes and full cue coverage; editing either source
file invalidates its previous review. Review reports are workflow artifacts,
not cryptographically trusted attestations; do not hand-edit them to pass a build.

HTTP 429/529/503 responses retry at most twice with short bounded backoff.
Authentication, invalid response and other HTTP errors stop. Connection failures
are not automatically retried because the service may already have processed the
request. Error bodies are not printed or saved. Token usage covers valid returned
responses only, not uncertain or failed attempts; it is not a billing statement.

## Offline tests

```bash
"$PY" -m unittest discover -s "$SKILL_DIR/tests" -v
```

Tests use synthetic subtitles and mocked HTTP responses, not real API calls.

## API references

- [API contract](https://docs.typesafe.ai/api)
- [Choice](https://docs.typesafe.ai/primitives/choice)
- [State and language limitations](https://docs.typesafe.ai/concepts/state)
- [Confidence](https://docs.typesafe.ai/confidence)
