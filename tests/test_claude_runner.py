import subprocess
import pytest
from marwin import claude_runner as cr


def _fake_run(stdout="", rc=0, exc=None):
    def fake(cmd, **kwargs):
        assert cmd == "claude -p"
        assert kwargs.get("shell") is True
        assert kwargs.get("encoding") == "utf-8"
        if exc:
            raise exc
        class R:
            returncode = rc
            stderr = "boom" if rc else ""
        R.stdout = stdout
        return R
    return fake


def test_run_claude_returns_stdout(monkeypatch):
    monkeypatch.setattr(cr.subprocess, "run", _fake_run(stdout="  hello  "))
    assert cr.run_claude("hi") == "hello"


def test_run_claude_nonzero_raises(monkeypatch):
    monkeypatch.setattr(cr.subprocess, "run", _fake_run(rc=1))
    with pytest.raises(cr.ClaudeError, match="rc=1"):
        cr.run_claude("hi")


def test_run_claude_timeout_raises(monkeypatch):
    exc = subprocess.TimeoutExpired("claude -p", 5)
    monkeypatch.setattr(cr.subprocess, "run", _fake_run(exc=exc))
    with pytest.raises(cr.ClaudeError, match="timed out"):
        cr.run_claude("hi", timeout_s=5)


def test_extract_json_array_with_noise():
    assert cr.extract_json('note\n[{"a": 1}]\nthanks') == [{"a": 1}]


def test_extract_json_object_containing_array():
    assert cr.extract_json('{"items": [1, 2]}') == {"items": [1, 2]}


def test_extract_json_none_raises():
    with pytest.raises(cr.ClaudeError, match="no JSON"):
        cr.extract_json("sorry, no data")


def test_extract_json_ignores_trailing_brace_noise():
    assert cr.extract_json('[{"a": 1}] hope the {} helps!') == [{"a": 1}]


def test_extract_json_object_with_trailing_brace_noise():
    # rfind regression: a stray closing brace in trailing prose must not
    # extend the parsed slice past the real JSON value.
    assert cr.extract_json('{"a": 1} hope the {} helps!') == {"a": 1}


def test_run_claude_empty_stdout_raises(monkeypatch):
    monkeypatch.setattr(cr.subprocess, "run", _fake_run(stdout="   "))
    with pytest.raises(cr.ClaudeError, match="failed"):
        cr.run_claude("hi")


def test_run_claude_forwards_prompt(monkeypatch):
    seen = {}
    def fake(cmd, **kwargs):
        seen["input"] = kwargs.get("input")
        class R: returncode = 0; stdout = "ok"; stderr = ""
        return R
    monkeypatch.setattr(cr.subprocess, "run", fake)
    cr.run_claude("my exact prompt")
    assert seen["input"] == "my exact prompt"
