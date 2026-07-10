import json
from marwin.minutes import render_minutes_md, write_minutes

META = {"title": "team meeting", "date": "2026-07-10"}
META_WITH_TIME = {**META, "started_at": "2026-07-10T18:30:00"}

INTEL = {
    "title": "team meeting", "date": "2026-07-10",
    "summary": {
        "overview": "We planned the demo app work.",
        "by_topic": [
            {"topic": "demo app", "notes": ["**Setup** discussed.", "Next steps agreed."]},
            {"topic": "Ads research", "notes": "Old-shape single string note."},
        ],
        "outcomes": "Work assigned.",
    },
    "tasks": [
        {"task": "Compile survey results to Drive", "owner": "Alex", "deadline": "asap",
         "timestamp": 409, "quote": "do some research", "qa_score": 92, "qa_reason": "explicit"},
        {"task": "Fix the pipe | in report", "owner": "", "deadline": "",
         "timestamp": 410, "qa_score": 40, "qa_reason": "unclear"},
    ],
    "decisions": [
        {"decision": "Use the new logo for the demo app.", "decided_by": "Alex",
         "timestamp": 420, "qa_score": 90, "qa_reason": "explicit"},
    ],
    "questions": [
        {"question": "Which API?", "asked_by": "Alex", "answered": False,
         "timestamp": 500, "qa_score": 40, "qa_reason": "unclear"},
        {"question": "Already resolved one?", "asked_by": "Alex", "answered": True,
         "timestamp": 501, "qa_score": 95, "qa_reason": "explicit"},
    ],
    "risks": [
        {"risk": "Server capacity might be too low.", "raised_by": "Alex",
         "severity": "high", "timestamp": 378, "qa_score": 95, "qa_reason": "explicit"},
    ],
    "deadlines": [
        {"what": "send the draft", "when_text": "before Friday", "when_iso": None,
         "owner": "Alex", "timestamp": 378, "qa_score": 95, "qa_reason": "explicit"},
    ],
    "topics": [{"topic": "demo app", "start": 355, "end": 700},
               {"topic": "Ads research", "start": 700, "end": 900}],
}

# Same shape but with no risks and only an answered question -> both extra
# sections should be omitted.
INTEL_NO_EXTRAS = {**INTEL, "risks": [],
                   "questions": [{"question": "Already resolved?",
                                  "answered": True, "qa_score": 95}]}

# Agenda source (topics agent) empty -> must fall back to summary.by_topic.
INTEL_NO_TOPICS_AGENT = {**INTEL, "topics": []}

# Both agenda sources empty -> Agenda section omitted entirely.
INTEL_NO_AGENDA_AT_ALL = {**INTEL, "topics": [], "summary": {**INTEL["summary"], "by_topic": []}}

# No tasks / no decisions -> those sections omitted entirely.
INTEL_NO_TASKS_OR_DECISIONS = {**INTEL, "tasks": [], "decisions": []}


def test_header_block_exact():
    md = render_minutes_md(META, INTEL)
    assert md.startswith("# Minutes of Meeting (MoM)")
    assert "**Meeting Title:** team meeting" in md
    assert "**Date:** Friday, 10 July 2026" in md
    assert "**Time:** _(add time)_" in md   # no started_at -> placeholder
    assert "**Attendees:** _(add names)_" in md


def test_time_line_from_started_at():
    md = render_minutes_md(META_WITH_TIME, INTEL)
    assert "**Time:** 6:30 PM (PKT)" in md


def test_agenda_bullets_from_topics_agent():
    md = render_minutes_md(META, INTEL)
    assert "## Agenda" in md
    assert "* demo app" in md
    assert "* Ads research" in md


def test_agenda_falls_back_to_summary_by_topic_when_topics_agent_empty():
    md = render_minutes_md(META, INTEL_NO_TOPICS_AGENT)
    assert "## Agenda" in md
    assert "* demo app" in md
    assert "* Ads research" in md


def test_agenda_omitted_when_both_sources_empty():
    md = render_minutes_md(META, INTEL_NO_AGENDA_AT_ALL)
    assert "## Agenda" not in md


def test_discussion_summary_numbering_and_notes_shapes():
    md = render_minutes_md(META, INTEL)
    assert "## Discussion Summary" in md
    assert "### 1. demo app" in md
    assert "### 2. Ads research" in md
    # new shape: notes is a list -> one bullet per string
    assert "* **Setup** discussed." in md
    assert "* Next steps agreed." in md
    # old cached shape: notes is a single string -> one bullet
    assert "* Old-shape single string note." in md


def test_action_items_table_row_owner_deadline_and_flag():
    md = render_minutes_md(META, INTEL)
    assert "# Action Items" in md
    assert "| Task | Owner | Deadline |" in md
    assert "| Compile survey results to Drive | Alex | asap |" in md
    # qa_score 40 (< 70) task gets the warning prefix
    assert "| ⚠️ Fix the pipe \\| in report | — | — |" in md


def test_action_items_section_and_key_decisions_omitted_when_empty():
    md = render_minutes_md(META, INTEL_NO_TASKS_OR_DECISIONS)
    assert "# Action Items" not in md
    assert "## Key Decisions" not in md


def test_key_decisions_bullet():
    md = render_minutes_md(META, INTEL)
    assert "## Key Decisions" in md
    assert "* Use the new logo for the demo app." in md


def test_risks_and_open_questions_present_and_answered_excluded():
    md = render_minutes_md(META, INTEL)
    assert "## Risks" in md
    assert "* Server capacity might be too low. (high)" in md
    assert "## Open Questions" in md
    assert "⚠️ Which API?" in md
    assert "Already resolved one?" not in md  # answered -> excluded


def test_risks_and_open_questions_omitted_when_empty():
    md = render_minutes_md(META, INTEL_NO_EXTRAS)
    assert "## Risks" not in md
    assert "## Open Questions" not in md


def test_overview_and_outcomes_never_rendered():
    md = render_minutes_md(META, INTEL)
    assert "## Overview" not in md
    assert "## Outcomes" not in md
    assert "We planned the demo app work." not in md
    assert "Work assigned." not in md


def test_pipe_in_task_cell_is_escaped():
    md = render_minutes_md(META, INTEL)
    assert "Fix the pipe \\| in report" in md
    assert "Fix the pipe | in report" not in md


def test_renderer_tolerates_missing_optional_fields_defensively():
    """Cached/legacy items may lack their primary key entirely, carry
    non-dict elements, or omit whole sections; rendering must degrade
    gracefully, not crash."""
    meta = {"title": "t", "date": "2026-07-10"}
    intel = {
        "summary": None,
        "tasks": [{"timestamp": None}, "not a dict"],
        "decisions": [{}],
        "questions": [{}],
        "risks": [{}],
        "topics": [],
    }
    md = render_minutes_md(meta, intel)
    assert md.startswith("# Minutes of Meeting (MoM)")
    assert "**Meeting Title:** t" in md


def test_write_minutes_creates_only_markdown_and_returns_single_path(tmp_path):
    d = tmp_path / "m"; d.mkdir()
    (d / "meta.json").write_text(json.dumps(META))
    (d / "intelligence.json").write_text(
        json.dumps(INTEL, ensure_ascii=False), encoding="utf-8")
    md_path = write_minutes(d)
    assert md_path == d / "minutes.md"
    md = md_path.read_text(encoding="utf-8")
    assert md.startswith("# Minutes of Meeting (MoM)")
    assert "team meeting" in md
    assert not (d / "minutes.docx").exists()


def test_timestamps_stripped_from_agenda_and_notes():
    # User rule: minutes carry no [Ns] transcript markers.
    # Patterns mirror the marker shapes real model output produced.
    intel = {**INTEL, "summary": {**INTEL["summary"], "by_topic": [
        {"topic": "Analytics rollout [391s]", "notes": [
            "Both dashboards created in **TrackerApp** for review purposes **[33s]**",
            "Lead asked for them to be posted in **Slack [57s]**",
            "Clips must stay under **400 MB [334s]**",
        ]},
    ]}, "topics": [{"topic": "Dashboards **[33s]**"}]}
    md = render_minutes_md(META, intel)
    assert "[33s]" not in md and "[57s]" not in md
    assert "[334s]" not in md and "[391s]" not in md
    assert "****" not in md
    assert "* Both dashboards created in **TrackerApp** for review purposes" in md
    assert "* Lead asked for them to be posted in **Slack**" in md
    assert "* Clips must stay under **400 MB**" in md
    assert "### 1. Analytics rollout" in md
    assert "* Dashboards" in md
