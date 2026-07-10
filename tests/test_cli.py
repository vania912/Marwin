import pytest

from marwin.cli import build_parser, check_disk_space


def test_parser_record():
    args = build_parser().parse_args(["record", "--title", "sync"])
    assert args.command == "record" and args.title == "sync"


def test_parser_record_recover():
    args = build_parser().parse_args(["record", "--recover"])
    assert args.recover is True and args.title is None


def test_parser_process_default_meeting():
    args = build_parser().parse_args(["process"])
    assert args.command == "process" and args.meeting is None


def test_disk_check_fails_when_low(monkeypatch, tmp_path):
    import shutil, collections
    fake = collections.namedtuple("usage", "total used free")(100, 99, 1 * 2**30)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: fake)
    with pytest.raises(RuntimeError, match="2.0 GB"):
        check_disk_space(tmp_path, 2.0)


def test_parser_analyze():
    args = build_parser().parse_args(["analyze", "--force"])
    assert args.command == "analyze" and args.force and args.meeting is None


def test_parser_run():
    args = build_parser().parse_args(["run", "2026-07-10-team-meeting"])
    assert args.command == "run" and args.meeting == "2026-07-10-team-meeting"


def test_run_fallback_to_unanalyzed_when_no_unprocessed(monkeypatch, tmp_path):
    """Test that 'run' falls back to latest_unanalyzed when no unprocessed meetings exist."""
    import json
    from marwin.cli import main

    # Setup: Create a meeting with transcript.json but no intelligence.json (unanalyzed)
    meetings_root = tmp_path / "meetings"
    meetings_root.mkdir()
    meeting_dir = meetings_root / "2026-07-10-test-meeting"
    meeting_dir.mkdir()

    # Create meta.json and transcript.json (no audio.opus, no intelligence.json)
    meta = {"title": "Test Meeting", "date": "2026-07-10", "duration_s": None}
    (meeting_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (meeting_dir / "transcript.json").write_text('{"text": "test"}', encoding="utf-8")

    # Mock config to point to our test meetings_root
    def mock_load_config(root):
        return {"meetings_dir": "meetings", "recording": {"min_free_gb": 0.1}}

    monkeypatch.setattr("marwin.cli.load_config", mock_load_config)

    # Track calls
    analyze_called = []
    process_called = []

    def mock_analyze_meeting(meeting_dir, force=False):
        analyze_called.append(meeting_dir)
        return meeting_dir / "intelligence.json"

    def mock_process_meeting(meeting_dir, cfg, root):
        process_called.append(meeting_dir)
        raise AssertionError("process_meeting should not be called in this scenario")

    # Patch the actual import locations (not module-level, but imported within the function)
    monkeypatch.setattr("marwin.analyze.analyze_meeting", mock_analyze_meeting)
    monkeypatch.setattr("marwin.kaggle_runner.process_meeting", mock_process_meeting)

    # Set cwd to tmp_path so config loads relative to it
    monkeypatch.chdir(tmp_path)

    # Run the CLI
    result = main(["run"])

    # Assertions
    assert result == 0, "Should succeed"
    assert len(analyze_called) == 1, "analyze_meeting should be called once"
    assert len(process_called) == 0, "process_meeting should not be called"
    assert analyze_called[0] == meeting_dir, "Should analyze the unanalyzed meeting"
