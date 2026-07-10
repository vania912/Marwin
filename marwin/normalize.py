"""Script normalization — enforces HARD RULE 1: output is English (Latin)
and Urdu (Urdu script) ONLY; Devanagari must never survive this pass."""
import json

from .claude_runner import run_claude, extract_json


class NormalizeError(RuntimeError):
    pass


def contains_devanagari(text: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in text)


PROMPT = """You are normalizing meeting-transcript segments. The speaker uses ONLY Urdu and English (HARD RULE: Hindi/Devanagari script must never appear in your output).
The speech recognizer sometimes wrote Urdu in Devanagari (Hindi script) and sometimes spelled English words phonetically in the wrong script.
For EACH input segment return:
- "text": the segment restored to proper form — Urdu in Urdu (Arabic/Nastaliq) script, genuinely-English words and sentences in Latin letters. Zero Devanagari characters.
- "english": a clean, natural English rendering of the whole segment.
Keep the meaning faithful. Do not summarize, merge, or drop segments.
Return ONLY a JSON array of {"i": <same index>, "text": "...", "english": "..."} — no markdown, no commentary.

Segments:
"""

_RETRY_SUFFIX = ("\nIMPORTANT: your previous answer contained Devanagari "
                 "characters (U+0900-U+097F). That is forbidden. Rewrite any "
                 "Devanagari as Urdu script (Arabic letters) or English.")


def _batches(segments, max_chars: int = 4000):
    batch, size = [], 0
    for i, seg in enumerate(segments):
        n = len(seg["text"])
        if batch and size + n > max_chars:
            yield batch
            batch, size = [], 0
        batch.append((i, seg))
        size += n
    if batch:
        yield batch


def _run_batch(batch, run, stern: bool):
    payload = json.dumps([{"i": i, "text": s["text"]} for i, s in batch],
                         ensure_ascii=False)
    prompt = PROMPT + payload + (_RETRY_SUFFIX if stern else "")
    items = extract_json(run(prompt))
    if not isinstance(items, list):
        raise NormalizeError(f"expected JSON array, got {type(items).__name__}")
    return items


def normalize_segments(segments: list, run=run_claude) -> list:
    out = [dict(s) for s in segments]
    for batch in _batches(segments):
        items = _run_batch(batch, run, stern=False)
        if any(contains_devanagari(str(it.get("text", "")) + str(it.get("english", "")))
               for it in items):
            items = _run_batch(batch, run, stern=True)
            if any(contains_devanagari(str(it.get("text", "")) + str(it.get("english", "")))
                   for it in items):
                raise NormalizeError(
                    "Devanagari persisted after retry — HARD RULE 1 violated")
        by_index = {}
        for it in items:
            try:
                by_index[int(it["i"])] = it
            except (KeyError, ValueError, TypeError):
                raise NormalizeError(f"malformed normalization item: {it!r:.120}")
        for i, _seg in batch:
            if i not in by_index:
                raise NormalizeError(f"normalization missing segment index {i}")
            item = by_index[i]
            if "text" not in item or "english" not in item:
                raise NormalizeError(f"normalization item {i} missing text/english")
            out[i]["text"] = str(item["text"])
            out[i]["english"] = str(item["english"])
    return out
