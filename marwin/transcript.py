"""transcript.json schema + display helpers. Kaggle-safe: stdlib + jsonschema."""
import hashlib
import json
from pathlib import Path

import jsonschema

SCHEMA = {
    "type": "object",
    "required": ["duration", "model_info", "speakers", "segments"],
    "properties": {
        "duration": {"type": "number", "minimum": 0},
        "model_info": {"type": "object"},
        "speakers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "embedding"],
                "properties": {
                    "label": {"type": "string"},
                    "embedding": {"type": "array", "items": {"type": "number"}},
                },
            },
        },
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["start", "end", "speaker", "lang", "text", "confidence"],
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "speaker": {"type": "string"},
                    "lang": {"type": "string"},
                    "text": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    },
}


def validate(data: dict) -> None:
    jsonschema.validate(data, SCHEMA)


def save(path: Path, data: dict) -> None:
    validate(data)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def load(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(data)
    return data


def format_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


_PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52",
            "#8172B3", "#937860", "#DA8BC3", "#8C8C8C"]


def speaker_color(label: str) -> str:
    digest = hashlib.md5(label.encode("utf-8")).hexdigest()
    return _PALETTE[int(digest[:8], 16) % len(_PALETTE)]
