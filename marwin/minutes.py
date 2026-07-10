"""Minutes of Meeting rendering — the user's mandated MoM template (HARD RULE).
Markdown only — rendered inside the dashboard, no .docx (user rule change,
Task 11). The renderer only re-arranges what intelligence.json already
contains — no new transformations, no network."""
import datetime as dt
import json
import re
from pathlib import Path

from .meetings import read_meta

FLAG_BELOW = 70


def _flagged(item: dict) -> bool:
    score = item.get("qa_score")
    if score is None:
        score = 0
    return score < FLAG_BELOW


def _esc(text) -> str:
    """Escape '|' so it can't break a markdown table row."""
    return str(text if text is not None else "").replace("|", "\\|")


def _dict_items(items) -> list:
    return [i for i in (items or []) if isinstance(i, dict)]


_TS_BOLD = re.compile(r"\s*\*\*\[\d+\s*s\]\*\*")
_TS_BARE = re.compile(r"\s*\[\d+\s*s\]")


def _strip_ts(text: str) -> str:
    """Drop transcript [Ns] markers the summary agent may embed — user
    rule: minutes carry no timestamps. Handles '**[33s]**', '[33s]', and
    '**Slack [57s]**' (marker inside a bold span) without breaking bold."""
    text = _TS_BOLD.sub("", text)
    text = _TS_BARE.sub("", text)
    return text.replace("****", "").rstrip()


def _long_date(date_str: str) -> str:
    """'2026-07-10' -> 'Friday, 10 July 2026' (portable — no %-d on Windows)."""
    if not date_str:
        return ""
    try:
        d = dt.date.fromisoformat(date_str)
    except ValueError:
        return str(date_str)
    return f"{d:%A}, {d.day} {d:%B} {d.year}"


def _time_line(meta: dict) -> str:
    started_at = meta.get("started_at")
    if not started_at:
        return "_(add time)_"
    try:
        t = dt.datetime.fromisoformat(started_at)
    except ValueError:
        return "_(add time)_"
    time_str = t.strftime("%I:%M %p").lstrip("0")
    return f"{time_str} (PKT)"


def _header_block(meta: dict) -> str:
    title = meta.get("title") or ""
    long_date = _long_date(meta.get("date", ""))
    time_line = _time_line(meta)
    return "\n".join([
        "# Minutes of Meeting (MoM)",
        "",
        f"**Meeting Title:** {title}",
        f"**Date:** {long_date}",
        f"**Time:** {time_line}",
        "**Attendees:** _(add names)_",
    ])


def _agenda_items(intel: dict) -> list:
    topics = _dict_items(intel.get("topics"))
    items = [t.get("topic") or "" for t in topics]
    if not items:
        by_topic = _dict_items((intel.get("summary") or {}).get("by_topic"))
        items = [t.get("topic") or "" for t in by_topic]
    return items


def _agenda_block(agenda_items: list) -> str:
    return "\n".join(["## Agenda", ""]
                     + [f"* {_strip_ts(item)}" for item in agenda_items])


def _topic_notes(topic: dict) -> list:
    notes = topic.get("notes")
    if isinstance(notes, list):
        return [_strip_ts(n) for n in notes if isinstance(n, str)]
    if isinstance(notes, str) and notes:
        return [_strip_ts(notes)]
    return []


def _discussion_block(by_topic: list) -> str:
    chunks = []
    for idx, t in enumerate(by_topic, start=1):
        chunk_lines = [f"### {idx}. {_strip_ts(t.get('topic') or '')}", ""]
        chunk_lines += [f"* {n}" for n in _topic_notes(t)]
        chunks.append("\n".join(chunk_lines))
    return "## Discussion Summary\n\n" + "\n\n".join(chunks)


def _task_row(task: dict) -> str:
    task_cell = _esc(task.get("task") or "")
    if _flagged(task):
        task_cell = f"⚠️ {task_cell}"
    owner = _esc(task.get("owner") or "") or "—"
    deadline = _esc(task.get("deadline") or "") or "—"
    return f"| {task_cell} | {owner} | {deadline} |"


def _action_items_block(tasks: list) -> str:
    lines = ["# Action Items", "",
             "| Task | Owner | Deadline |",
             "| ---- | ----- | -------- |"]
    lines += [_task_row(t) for t in tasks]
    return "\n".join(lines)


def _key_decisions_block(decisions: list) -> str:
    lines = ["## Key Decisions", ""]
    lines += [f"* {d.get('decision') or ''}" for d in decisions]
    return "\n".join(lines)


def _risk_line(r: dict) -> str:
    text = r.get("risk") or ""
    if r.get("severity"):
        text = f"{text} ({r['severity']})"
    return f"⚠️ {text}" if _flagged(r) else text


def _question_line(q: dict) -> str:
    text = q.get("question") or ""
    return f"⚠️ {text}" if _flagged(q) else text


def _extras_block(risks: list, questions: list) -> str:
    parts = []
    if risks:
        parts.append("\n".join(["## Risks", ""] + [f"* {_risk_line(r)}" for r in risks]))
    if questions:
        parts.append("\n".join(["## Open Questions", ""] + [f"* {_question_line(q)}" for q in questions]))
    return "\n\n".join(parts)


def render_minutes_md(meta: dict, intel: dict) -> str:
    meta = meta or {}
    intel = intel or {}

    blocks = [_header_block(meta)]

    agenda_items = _agenda_items(intel)
    if agenda_items:
        blocks.append(_agenda_block(agenda_items))

    by_topic = _dict_items((intel.get("summary") or {}).get("by_topic"))
    if by_topic:
        blocks.append(_discussion_block(by_topic))

    tasks = _dict_items(intel.get("tasks"))
    if tasks:
        blocks.append(_action_items_block(tasks))

    decisions = [d for d in _dict_items(intel.get("decisions")) if d.get("decision")]
    if decisions:
        blocks.append(_key_decisions_block(decisions))

    risks = _dict_items(intel.get("risks"))
    questions = [q for q in _dict_items(intel.get("questions")) if not q.get("answered")]
    extras = _extras_block(risks, questions)
    if extras:
        blocks.append(extras)

    return "\n\n---\n\n".join(blocks) + "\n"


def write_minutes(meeting_dir: Path) -> Path:
    meeting_dir = Path(meeting_dir)
    meta = read_meta(meeting_dir)
    intel = json.loads((meeting_dir / "intelligence.json")
                       .read_text(encoding="utf-8"))
    md = render_minutes_md(meta, intel)
    md_path = meeting_dir / "minutes.md"
    md_path.write_text(md, encoding="utf-8")
    return md_path
