"""Shared subtitle input validation and deterministic formatting (stdlib only)."""
import hashlib
import json
import math
from pathlib import Path

MAX_LINE = 24


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key in input")
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=_unique_object)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def load_inputs(sent_path, tr_path):
    units, translations = read_json(sent_path), read_json(tr_path)
    if not isinstance(units, list) or not units:
        raise ValueError("Sentences must be a non-empty JSON array")
    if not isinstance(translations, dict):
        raise ValueError("Translations must be an id-to-text JSON object")
    ids, previous_id, previous_end = set(), 0, 0.0
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError("Each sentence must be an object")
        uid, start, end = unit.get("id"), unit.get("start"), unit.get("end")
        if type(uid) is not int or uid <= previous_id:
            raise ValueError("Unit ids must be positive, unique and increasing")
        if not finite_number(start) or not finite_number(end) or start < 0 or end <= start:
            raise ValueError(f"Invalid time range for unit {uid}")
        if start < previous_end:
            raise ValueError(f"Overlapping time range for unit {uid}")
        if not isinstance(unit.get("en"), str) or not unit["en"].strip():
            raise ValueError(f"Missing English text for unit {uid}")
        korean = translations.get(str(uid))
        if not isinstance(korean, str) or not korean.strip():
            raise ValueError(f"Missing or empty translation for unit {uid}")
        if any(c in korean for c in ("\n", "\r", "\x00")):
            raise ValueError(f"Translation {uid} must be one text line; wrapping is automatic")
        ids.add(str(uid))
        previous_id, previous_end = uid, end
    if set(translations) != ids:
        raise ValueError("Translations contain ids absent from the transcript")
    return units, translations


def wrap(text):
    if len(text) <= MAX_LINE:
        return text
    mid = len(text) // 2
    candidates = [p for p in (text.rfind(" ", 0, mid), text.find(" ", mid)) if p != -1]
    if not candidates:
        return text
    split = min(candidates, key=lambda p: abs(p - mid))
    return text[:split].strip() + "\n" + text[split:].strip()


def fmt(seconds, separator):
    total_ms = round(seconds * 1000)
    seconds, ms = divmod(total_ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{ms:03d}"
