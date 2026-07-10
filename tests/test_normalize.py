import json
import pytest
from marwin.normalize import (contains_devanagari, normalize_segments,
                              NormalizeError, _batches)

SEGS = [
    {"start": 0.0, "end": 2.0, "speaker": "Alex", "lang": "ur",
     "text": "मैंने ब्लूप्रिंट complete कर लिया", "confidence": 0.8},
    {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_00", "lang": "en",
     "text": "sounds good", "confidence": 0.9},
]


def test_contains_devanagari():
    assert contains_devanagari("मैंने") is True
    assert contains_devanagari("میں نے blueprint") is False


def test_batches_respect_max_chars():
    segs = [{"text": "x" * 50} for _ in range(10)]
    batches = list(_batches(segs, max_chars=120))
    assert all(sum(len(s["text"]) for _, s in b) <= 120 for b in batches)
    assert sum(len(b) for b in batches) == 10


def _good_run(prompt):
    payload = json.loads(prompt[prompt.find("["):prompt.rfind("]") + 1])
    return json.dumps([{"i": item["i"],
                        "text": "میں نے blueprint complete کر لیا",
                        "english": "I completed the blueprint"}
                       for item in payload], ensure_ascii=False)


def test_normalize_replaces_text_and_adds_english():
    out = normalize_segments(SEGS, run=_good_run)
    assert out[0]["text"] == "میں نے blueprint complete کر لیا"
    assert out[0]["english"] == "I completed the blueprint"
    assert "english" in out[1]
    assert SEGS[0]["text"].startswith("मैंने")  # input not mutated


def test_normalize_rejects_persistent_devanagari():
    def bad_run(prompt):
        payload = json.loads(prompt[prompt.find("["):prompt.rfind("]") + 1])
        return json.dumps([{"i": it["i"], "text": "मैंने", "english": "x"}
                           for it in payload], ensure_ascii=False)
    with pytest.raises(NormalizeError, match="Devanagari"):
        normalize_segments(SEGS, run=bad_run)


def test_normalize_retries_once_then_succeeds():
    calls = {"n": 0}
    def flaky_run(prompt):
        calls["n"] += 1
        payload = json.loads(prompt[prompt.find("["):prompt.rfind("]") + 1])
        text = "मैंने" if calls["n"] == 1 else "میں نے"
        return json.dumps([{"i": it["i"], "text": text, "english": "ok"}
                           for it in payload], ensure_ascii=False)
    out = normalize_segments(SEGS, run=flaky_run)
    assert calls["n"] == 2
    assert out[0]["text"] == "میں نے"


def test_normalize_missing_index_raises():
    def partial_run(prompt):
        return json.dumps([{"i": 0, "text": "ok", "english": "ok"}])
    with pytest.raises(NormalizeError, match="missing"):
        normalize_segments(SEGS, run=partial_run)


def test_normalize_accepts_string_indices():
    def run_str_i(prompt):
        payload = json.loads(prompt[prompt.find("["):prompt.rfind("]") + 1])
        return json.dumps([{"i": str(it["i"]), "text": "ok", "english": "ok"}
                           for it in payload])
    out = normalize_segments(SEGS, run=run_str_i)
    assert out[0]["text"] == "ok"


def test_normalize_item_missing_english_raises():
    def run_no_english(prompt):
        payload = json.loads(prompt[prompt.find("["):prompt.rfind("]") + 1])
        return json.dumps([{"i": it["i"], "text": "ok"} for it in payload])
    with pytest.raises(NormalizeError, match="missing text/english"):
        normalize_segments(SEGS, run=run_no_english)
