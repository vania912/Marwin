import datetime as dt
import json
from marwin.meetings import (
    slugify, create_meeting_dir, read_meta, update_meta,
    list_meetings, latest_unprocessed,
)

DATE = dt.date(2026, 7, 9)

def test_slugify():
    assert slugify("Team Sync!  (Weekly)") == "team-sync-weekly"

def test_create_meeting_dir_and_meta(tmp_path):
    d = create_meeting_dir(tmp_path, "Team Sync", DATE)
    assert d.name == "2026-07-09-team-sync"
    meta = read_meta(d)
    assert meta["title"] == "Team Sync"
    assert meta["date"] == "2026-07-09"
    assert meta["duration_s"] is None

def test_create_meeting_dir_stamps_started_at(tmp_path):
    d = create_meeting_dir(tmp_path, "Team Sync", DATE)
    meta = read_meta(d)
    assert "started_at" in meta
    # must be a parseable ISO timestamp (record flow's minutes renderer relies on this)
    dt.datetime.fromisoformat(meta["started_at"])

def test_collision_gets_suffix(tmp_path):
    create_meeting_dir(tmp_path, "Sync", DATE)
    d2 = create_meeting_dir(tmp_path, "Sync", DATE)
    assert d2.name == "2026-07-09-sync-2"

def test_update_meta(tmp_path):
    d = create_meeting_dir(tmp_path, "Sync", DATE)
    update_meta(d, duration_s=61.5)
    assert read_meta(d)["duration_s"] == 61.5

def test_list_and_latest_unprocessed(tmp_path):
    d1 = create_meeting_dir(tmp_path, "Old", dt.date(2026, 7, 1))
    d2 = create_meeting_dir(tmp_path, "New", DATE)
    (d1 / "audio.opus").write_bytes(b"x")
    (d1 / "transcript.json").write_text("{}")
    (d2 / "audio.opus").write_bytes(b"x")
    ms = list_meetings(tmp_path)
    assert [m["title"] for m in ms] == ["New", "Old"]
    assert ms[1]["has_transcript"] is True
    assert latest_unprocessed(tmp_path) == d2

def test_latest_unanalyzed(tmp_path):
    from marwin.meetings import latest_unanalyzed
    d1 = create_meeting_dir(tmp_path, "done", dt.date(2026, 7, 1))
    d2 = create_meeting_dir(tmp_path, "todo", dt.date(2026, 7, 9))
    for d in (d1, d2):
        (d / "transcript.json").write_text("{}")
    (d1 / "intelligence.json").write_text("{}")
    assert latest_unanalyzed(tmp_path) == d2
    (d2 / "intelligence.json").write_text("{}")
    assert latest_unanalyzed(tmp_path) is None
