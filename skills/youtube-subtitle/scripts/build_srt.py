#!/usr/bin/env python
"""Assemble a Korean SRT/VTT from unit timings + Korean translations.

Inputs (JSON):
  SENTENCES : [{id,start,end,en}]     produced by transcribe.py
  TRANSLATIONS : {"1":"...", "2":"..."}  id -> Korean text (you write this)

Output:
  <base>.ko.srt / <base>.ko.vtt   -- original timings preserved, long lines
                                     wrapped to 2 display lines.

Usage:
  python build_srt.py SENTENCES TRANSLATIONS OUT_DIR BASE [--accept-review-flags]

Requires OUT_DIR/BASE.review.json from review_subtitles.py for these exact inputs.
"""
import argparse
from pathlib import Path

from subtitle_common import file_hash, fmt, load_inputs, read_json, wrap


def require_review(path, sent_path, tr_path, units, accept_flags):
    report = read_json(path)
    if not isinstance(report, dict) or report.get("version") != 1 or report.get("status") != "completed":
        raise ValueError("A completed Jev review is required; failed, partial and dry-run reports cannot build subtitles")
    expected = {"sentences_sha256": file_hash(sent_path), "translations_sha256": file_hash(tr_path)}
    if report.get("inputs") != expected:
        raise ValueError("Review is stale: inputs changed. Run review_subtitles.py again")
    results = report.get("results", [])
    if (not isinstance(results, list) or not results or
            len(results) != report.get("window_count") or
            any(not isinstance(result, dict) or not isinstance(result.get("ids"), list) for result in results)):
        raise ValueError("Review window coverage is incomplete")
    if [uid for result in results for uid in result["ids"]] != [u["id"] for u in units]:
        raise ValueError("Review does not cover every subtitle in order")
    if "review_ids" not in report:
        raise ValueError("Invalid review report")
    if report["review_ids"] and not accept_flags:
        raise ValueError("Read the review report and re-check flagged cues. After resolving them, rerun review; "
                         "use --accept-review-flags only for flags you reviewed and chose to retain")


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("sentences", type=Path)
    cli.add_argument("translations", type=Path)
    cli.add_argument("out_dir", type=Path)
    cli.add_argument("base")
    cli.add_argument("--accept-review-flags", action="store_true")
    args = cli.parse_args(argv)
    if not args.base or Path(args.base).name != args.base or args.base in (".", ".."):
        raise ValueError("BASE must be a filename stem, not a path")
    units, ko = load_inputs(args.sentences, args.translations)
    require_review(args.out_dir / f"{args.base}.review.json", args.sentences,
                   args.translations, units, args.accept_review_flags)

    srt, vtt = [], ["WEBVTT", ""]
    for i, u in enumerate(units, 1):
        text = wrap(ko[str(u["id"])].strip())
        start = u["start"]
        end = u["end"]
        srt.append(f"{i}\n{fmt(start, ',')} --> {fmt(end, ',')}\n{text}\n")
        vtt.append(f"{i}\n{fmt(start, '.')} --> {fmt(end, '.')}\n{text}\n")

    (args.out_dir / f"{args.base}.ko.srt").write_text("\n".join(srt), encoding="utf-8")
    (args.out_dir / f"{args.base}.ko.vtt").write_text("\n".join(vtt), encoding="utf-8")
    print(f"OK: wrote {len(units)} cues -> {args.base}.ko.srt / {args.base}.ko.vtt")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        raise SystemExit(f"Cannot build subtitles: {error}")
