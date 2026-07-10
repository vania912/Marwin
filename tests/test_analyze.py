import json
from pathlib import Path
import pytest
from marwin import analyze as az
from marwin import transcript as t
from marwin.claude_runner import ClaudeError

TRANSCRIPT = {
    "duration": 30.0, "model_info": {"whisper": "large-v3"},
    "speakers": [],
    "segments": [
        {"start": 1.0, "end": 3.0, "speaker": "Alex", "lang": "en",
         "text": "hello", "confidence": 0.9},
        {"start": 5.0, "end": 9.0, "speaker": "SPEAKER_02", "lang": "en",
         "text": "send the draft before Friday", "confidence": 0.7},
    ],
}


def _meeting(tmp_path) -> Path:
    d = tmp_path / "2026-07-10-test"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps(
        {"title": "test", "date": "2026-07-10", "duration_s": 30.0}))
    t.save(d / "transcript.json", TRANSCRIPT)
    return d


def _fake_run(prompt: str) -> str:
    if "normalizing meeting-transcript segments" in prompt:
        payload = json.loads(prompt[prompt.find("["):prompt.rfind("]") + 1])
        return json.dumps([{"i": it["i"], "text": it["text"],
                            "english": it["text"] + " (en)"} for it in payload])
    if "QA agent" in prompt:
        return '[{"id": "deadlines-0", "score": 95, "reason": "explicit"}]'
    if "Deadline extraction agent" in prompt:
        return ('[{"what": "send the draft", "when_text": "before Friday", '
                '"when_iso": null, "owner": "Alex", "timestamp": 5}]')
    if "Minutes summary agent" in prompt:
        return '{"overview": "short test", "by_topic": [], "outcomes": "none"}'
    return "[]"


def test_analyze_writes_all_artifacts(tmp_path):
    d = _meeting(tmp_path)
    out = az.analyze_meeting(d, run=_fake_run)
    assert out == d / "intelligence.json"
    intel = json.loads(out.read_text(encoding="utf-8"))
    assert intel["deadlines"][0]["when_text"] == "before Friday"
    assert intel["deadlines"][0]["qa_score"] == 95
    assert intel["summary"]["overview"] == "short test"
    assert intel["tasks"] == []
    norm = json.loads((d / "analysis" / "normalized.json").read_text(encoding="utf-8"))
    assert norm["segments"][0]["english"] == "hello (en)"
    assert (d / "analysis" / "deadlines.json").exists()
    assert (d / "analysis" / "qa.json").exists()


def test_analyze_resumes_without_rerunning(tmp_path):
    d = _meeting(tmp_path)
    calls = {"n": 0}
    def counting_run(prompt):
        calls["n"] += 1
        return _fake_run(prompt)
    az.analyze_meeting(d, run=counting_run)
    first = calls["n"]
    az.analyze_meeting(d, run=counting_run)  # everything cached
    assert calls["n"] == first  # zero new Claude calls (HARD RULE 3)


def test_analyze_force_reruns(tmp_path):
    d = _meeting(tmp_path)
    calls = {"n": 0}
    def counting_run(prompt):
        calls["n"] += 1
        return _fake_run(prompt)
    az.analyze_meeting(d, run=counting_run)
    first = calls["n"]
    az.analyze_meeting(d, run=counting_run, force=True)
    assert calls["n"] == 2 * first


AGENT_MARKERS = {
    "tasks": "Action-Item extraction agent",
    "decisions": "Decision extraction agent",
    "questions": "Open-Question extraction agent",
    "risks": "Risk extraction agent",
    "deadlines": "Deadline extraction agent",
    "topics": "Topic segmentation agent",
    "summary": "Minutes summary agent",
}


def _marker_for(prompt):
    for name, marker in AGENT_MARKERS.items():
        if marker in prompt:
            return name
    return None


def test_analyze_resumes_after_one_agent_failure(tmp_path):
    """Ledger gap: one agent fails first run (others cache); a second run
    with a working fake only re-calls the missing agent (+qa+assembly).

    The failing agent is deliberately the LAST one submitted (dict order in
    AGENTS: tasks, decisions, questions, risks, deadlines, topics, summary)
    so every other agent's future is already resolved (and its ThreadPool
    result already retrieved) by the time the failure surfaces — avoiding a
    ThreadPoolExecutor.map race where not-yet-started futures queued after
    a failing one get cancelled rather than run."""
    d = _meeting(tmp_path)
    calls = {name: 0 for name in AGENT_MARKERS}

    def flaky_run(prompt):
        name = _marker_for(prompt)
        if name:
            calls[name] += 1
            if name == "summary":
                raise ClaudeError("simulated agent failure")
        return _fake_run(prompt)

    with pytest.raises(ClaudeError):
        az.analyze_meeting(d, run=flaky_run)

    for name in AGENT_MARKERS:
        assert calls[name] == 1, f"{name} called {calls[name]} times"
    for name in AGENT_MARKERS:
        if name != "summary":
            assert (d / "analysis" / f"{name}.json").exists()
    assert not (d / "analysis" / "summary.json").exists()
    assert not (d / "analysis" / "qa.json").exists()
    assert not (d / "intelligence.json").exists()

    calls2 = {name: 0 for name in AGENT_MARKERS}

    def working_run(prompt):
        name = _marker_for(prompt)
        if name:
            calls2[name] += 1
        return _fake_run(prompt)

    az.analyze_meeting(d, run=working_run)

    assert calls2["summary"] == 1        # only the missing agent re-called
    for name in AGENT_MARKERS:
        if name != "summary":
            assert calls2[name] == 0     # cached agents are not re-run
    assert (d / "analysis" / "summary.json").exists()
    assert (d / "analysis" / "qa.json").exists()
    assert (d / "intelligence.json").exists()


def test_save_normal_write_leaves_no_tmp_and_full_content(tmp_path):
    path = tmp_path / "y.json"
    az._save(path, {"a": [1, 2, 3]})
    assert not (tmp_path / "y.tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": [1, 2, 3]}


def test_analyze_raises_on_devanagari_in_assembled_intelligence(tmp_path):
    d = _meeting(tmp_path)

    def bad_run(prompt):
        if "Action-Item extraction agent" in prompt:
            return '[{"task": "नमस्ते do the thing", "timestamp": 1}]'
        return _fake_run(prompt)

    with pytest.raises(az.NormalizeError, match="Devanagari"):
        az.analyze_meeting(d, run=bad_run)
    assert not (d / "intelligence.json").exists()


def test_save_crash_mid_write_leaves_old_content_intact(tmp_path, monkeypatch):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"old": True}), encoding="utf-8")
    orig_write_text = Path.write_text

    def crash_write_text(self, *a, **kw):
        if self.suffix == ".tmp":
            raise OSError("simulated crash mid-write")
        return orig_write_text(self, *a, **kw)

    monkeypatch.setattr(Path, "write_text", crash_write_text)
    with pytest.raises(OSError):
        az._save(path, {"new": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert not (tmp_path / "x.tmp").exists()
