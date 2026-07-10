import json
import pytest
from marwin.agents import (render_transcript, AGENTS, run_agent,
                           score_items)
from marwin.claude_runner import ClaudeError

SEGS = [
    {"start": 12.3, "end": 15.0, "speaker": "Alex", "lang": "en",
     "text": "salam", "english": "Hello everyone", "confidence": 0.9},
    {"start": 378.0, "end": 383.0, "speaker": "SPEAKER_02", "lang": "en",
     "text": "send the draft before Friday", "confidence": 0.6},
]


def test_render_transcript_prefers_english():
    text = render_transcript(SEGS)
    lines = text.splitlines()
    assert lines[0] == "[12s] Alex: Hello everyone"
    assert lines[1] == "[378s] SPEAKER_02: send the draft before Friday"


def test_registry_has_all_seven_agents():
    assert set(AGENTS) == {"tasks", "decisions", "questions", "risks",
                           "deadlines", "topics", "summary"}
    for name, spec in AGENTS.items():
        assert "{transcript}" in spec["prompt"], name
        assert spec["kind"] in ("array", "object")


def test_run_agent_returns_parsed_array():
    def fake(prompt):
        assert "[378s] SPEAKER_02" in prompt
        return '[{"task": "compile the survey results", "owner": "Alex", "timestamp": 378}]'
    items = run_agent("tasks", render_transcript(SEGS), {"title": "t"}, run=fake)
    assert items[0]["task"] == "compile the survey results"


def test_run_agent_wrong_kind_retries_then_raises():
    calls = {"n": 0}
    def fake(prompt):
        calls["n"] += 1
        return '{"oops": true}'  # object where array expected
    with pytest.raises(ClaudeError, match="expected array"):
        run_agent("tasks", "x", {"title": "t"}, run=fake)
    assert calls["n"] == 2


def test_score_items_maps_ids():
    def fake(prompt):
        assert "tasks-0" in prompt
        return '[{"id": "tasks-0", "score": 88, "reason": "quoted directly"}]'
    scores = score_items([{"id": "tasks-0", "type": "tasks",
                           "claim": "compile the survey results"}], "transcript", run=fake)
    assert scores["tasks-0"]["score"] == 88


def test_run_agent_rejects_array_of_strings_then_retries():
    calls = {"n": 0}
    def fake(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return '["not a dict", "also not a dict"]'
        return '[{"task": "compile the survey results", "timestamp": 1}]'
    items = run_agent("tasks", "x", {"title": "t"}, run=fake)
    assert items[0]["task"] == "compile the survey results"
    assert calls["n"] == 2


def test_run_agent_raises_after_two_bad_element_shapes():
    def fake(prompt):
        return '["not a dict"]'
    with pytest.raises(ClaudeError, match="tasks"):
        run_agent("tasks", "x", {"title": "t"}, run=fake)


def test_run_agent_rejects_missing_required_key_then_retries():
    calls = {"n": 0}
    def fake(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return '[{"owner": "Alex"}]'  # missing "task"
        return '[{"task": "do it"}]'
    items = run_agent("tasks", "x", {"title": "t"}, run=fake)
    assert items[0]["task"] == "do it"
    assert calls["n"] == 2


def test_run_agent_rejects_null_required_value_then_retries():
    calls = {"n": 0}
    def fake(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return '[{"task": null}]'
        return '[{"task": "do it"}]'
    items = run_agent("tasks", "x", {"title": "t"}, run=fake)
    assert items[0]["task"] == "do it"


def test_run_agent_summary_requires_overview_key():
    calls = {"n": 0}
    def fake(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"by_topic": []}'  # missing "overview"
        return '{"overview": "short summary"}'
    result = run_agent("summary", "x", {"title": "t"}, run=fake)
    assert result["overview"] == "short summary"


def test_run_agent_retries_on_unparseable_json_then_succeeds():
    calls = {"n": 0}
    def fake(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return "sorry, I can't help with that."
        return '[{"task": "do it"}]'
    items = run_agent("tasks", "x", {"title": "t"}, run=fake)
    assert items[0]["task"] == "do it"
    assert calls["n"] == 2


def test_run_agent_raises_after_two_unparseable_replies():
    def fake(prompt):
        return "no json anywhere in this reply"
    with pytest.raises(ClaudeError):
        run_agent("tasks", "x", {"title": "t"}, run=fake)


def test_run_agent_cli_failure_propagates_immediately_no_retry():
    calls = {"n": 0}
    def fake(prompt):
        calls["n"] += 1
        raise ClaudeError("claude -p failed (rc=1): boom")
    with pytest.raises(ClaudeError, match="boom"):
        run_agent("tasks", "x", {"title": "t"}, run=fake)
    assert calls["n"] == 1  # no retry on a CLI-level failure


def test_score_items_skips_non_dict_and_bad_score_elements():
    def fake(prompt):
        return ('[{"id": "tasks-0", "score": "not-a-number", "reason": "x"}, '
                '"not a dict", '
                '{"id": "tasks-1", "score": "88.5", "reason": "ok"}]')
    scores = score_items([{"id": "tasks-0", "type": "tasks", "claim": "c"},
                          {"id": "tasks-1", "type": "tasks", "claim": "c2"}],
                         "transcript", run=fake)
    assert "tasks-0" not in scores
    assert scores["tasks-1"]["score"] == 88
