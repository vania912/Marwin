import pytest
import jsonschema
from marwin.transcript import validate, save, load, format_ts, speaker_color

GOOD = {
    "duration": 120.5,
    "model_info": {"whisper": "large-v3", "diarization": "pyannote-3.1"},
    "speakers": [{"label": "S1", "embedding": [0.1, 0.2]}],
    "segments": [
        {"start": 0.0, "end": 2.5, "speaker": "Alex", "lang": "en",
         "text": "hello", "confidence": 0.93},
    ],
}


def test_validate_good():
    validate(GOOD)  # must not raise


def test_validate_rejects_missing_speaker():
    bad = {**GOOD, "segments": [{"start": 0, "end": 1, "lang": "en",
                                 "text": "x", "confidence": 0.5}]}
    with pytest.raises(jsonschema.ValidationError):
        validate(bad)


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "transcript.json"
    save(p, GOOD)
    assert load(p)["segments"][0]["text"] == "hello"


def test_format_ts():
    assert format_ts(75.3) == "01:15"
    assert format_ts(0) == "00:00"


def test_speaker_color_stable_hex():
    c1, c2 = speaker_color("Alex"), speaker_color("Alex")
    assert c1 == c2 and c1.startswith("#") and len(c1) == 7
