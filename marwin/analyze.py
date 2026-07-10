"""ANALYZE stage orchestrator: normalize -> agents -> QA -> intelligence.json.
Every Claude output is cached to disk; re-runs only do what's missing
(HARD RULE 3: free/efficient — never re-spend quota)."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import transcript as transcript_mod
from .agents import AGENTS, render_transcript, run_agent, score_items
from .claude_runner import run_claude
from .meetings import read_meta
from .minutes import write_minutes
from .normalize import contains_devanagari, normalize_segments, NormalizeError

ARRAY_AGENTS = ("tasks", "decisions", "questions", "risks", "deadlines", "topics")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data) -> None:
    """Write JSON atomically: a crash mid-write must never leave a
    truncated file behind, since resume logic trusts these caches."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)


def analyze_meeting(meeting_dir: Path, run=run_claude, max_workers: int = 2,
                    force: bool = False) -> Path:
    meeting_dir = Path(meeting_dir)
    meta = read_meta(meeting_dir)
    data = transcript_mod.load(meeting_dir / "transcript.json")
    analysis = meeting_dir / "analysis"
    analysis.mkdir(exist_ok=True)

    norm_path = analysis / "normalized.json"
    if force or not norm_path.exists():
        print("normalizing scripts (en/ur hard rule)...")
        segments = normalize_segments(data["segments"], run=run)
        _save(norm_path, {"segments": segments})
    segments = _load(norm_path)["segments"]
    ttext = render_transcript(segments)

    def _one(name: str):
        out_path = analysis / f"{name}.json"
        if not force and out_path.exists():
            return
        print(f"agent: {name}...")
        items = run_agent(name, ttext, meta, run=run)
        _save(out_path, {"agent": name, "items": items})

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_one, list(AGENTS)))

    results = {name: _load(analysis / f"{name}.json")["items"]
               for name in AGENTS}

    qa_path = analysis / "qa.json"
    if force or not qa_path.exists():
        numbered = []
        for name in ARRAY_AGENTS:
            for idx, item in enumerate(results[name]):
                claim = json.dumps(item, ensure_ascii=False)
                numbered.append({"id": f"{name}-{idx}", "type": name,
                                 "claim": claim})
        scores = score_items(numbered, ttext, run=run) if numbered else {}
        _save(qa_path, scores)
    scores = _load(qa_path)

    intel = {"title": meta.get("title"), "date": meta.get("date"),
             "summary": results["summary"]}
    for name in ARRAY_AGENTS:
        merged = []
        for idx, item in enumerate(results[name]):
            qa = scores.get(f"{name}-{idx}", {"score": 0, "reason": "not scored"})
            merged.append({**item, "qa_score": qa["score"],
                           "qa_reason": qa["reason"]})
        intel[name] = merged

    if contains_devanagari(json.dumps(intel, ensure_ascii=False)):
        raise NormalizeError(
            "Devanagari detected in assembled intelligence — HARD RULE 1 violated")

    out = meeting_dir / "intelligence.json"
    _save(out, intel)
    write_minutes(meeting_dir)
    return out
