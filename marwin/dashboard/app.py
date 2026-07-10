"""Marwin dashboard — Phase 1: meetings list + transcript viewer.
Run via: marwin dashboard  (or: python3 -m streamlit run marwin/dashboard/app.py)"""
import html
from pathlib import Path

import streamlit as st

from marwin.config import load_config
from marwin.meetings import list_meetings
from marwin.transcript import load as load_transcript, format_ts, speaker_color


def _segment_html(seg: dict) -> str:
    """One transcript segment as an HTML line. User content is escaped."""
    color = speaker_color(seg["speaker"])
    lang_badge = " 🇵🇰" if seg["lang"] == "ur" else ""
    low_conf = " ⚠️" if seg["confidence"] < 0.5 else ""
    return (
        f"<div style='margin-bottom:6px'>"
        f"<code>{format_ts(seg['start'])}</code> "
        f"<b style='color:{color}'>{html.escape(seg['speaker'])}</b>{lang_badge}{low_conf} "
        f"{html.escape(seg['text'])}</div>"
    )


st.set_page_config(page_title="Marwin", page_icon="🎙️", layout="wide")

# Resolve the project root from this file's location (marwin/marwin/dashboard/
# app.py -> repo root) so the dashboard finds meetings no matter which
# directory streamlit was launched from — cwd broke with an empty dashboard.
root = Path(__file__).resolve().parents[2]
cfg = load_config(root)
meetings = list_meetings(root / cfg["meetings_dir"])

st.sidebar.title("🎙️ Marwin")
if not meetings:
    st.info("No meetings yet. Record one with:  `marwin record --title \"team sync\"`")
    st.stop()

labels = [f"{m['date']} — {m['title']}" for m in meetings]
choice = st.sidebar.radio("Meetings", labels, index=0)
meeting = meetings[labels.index(choice)]

st.title(meeting["title"])
sub = f"{meeting['date']}"
if meeting["duration_s"]:
    sub += f" · {format_ts(meeting['duration_s'])} long"
st.caption(sub)

if not meeting["has_transcript"]:
    st.warning("Not processed yet — run:  `marwin process`")
    st.stop()

data = load_transcript(meeting["dir"] / "transcript.json")
st.caption(f"Whisper: {data['model_info'].get('whisper', '?')} · "
           f"{len(data['segments'])} segments · "
           f"{len(data['speakers'])} detected speakers (+ you)")

analysis_dir = meeting["dir"] / "analysis"
norm_path = analysis_dir / "normalized.json"
intel_path = meeting["dir"] / "intelligence.json"

segments = data["segments"]
if norm_path.exists():
    import json as _json
    segments = _json.loads(norm_path.read_text(encoding="utf-8"))["segments"]
    mode = st.segmented_control("Language", ["Original", "English"],
                                default="Original",
                                label_visibility="collapsed")
    if mode == "English":
        segments = [{**s, "text": s.get("english", s["text"]), "lang": "en"}
                    for s in segments]

if intel_path.exists():
    import json as _json
    intel = _json.loads(intel_path.read_text(encoding="utf-8"))
    s = intel.get("summary") or {}
    if s.get("overview"):
        st.markdown(f"**Summary:** {html.escape(s['overview'])}")
    CARDS = [("📋 Action items", "tasks", "task"),
             ("✅ Decisions", "decisions", "decision"),
             ("⏰ Deadlines", "deadlines", "what"),
             ("⚠️ Risks", "risks", "risk"),
             ("❓ Open questions", "questions", "question")]
    for label, key, field in CARDS:
        items = intel.get(key) or []
        if key == "questions":
            items = [i for i in items if not i.get("answered")]
        if not items:
            continue
        with st.expander(f"{label} ({len(items)})",
                         expanded=key in ("tasks", "deadlines")):
            for i in items:
                flag = " ⚠️" if i.get("qa_score", 0) < 70 else ""
                extra = ""
                if i.get("owner"):
                    extra += f" — @{html.escape(i['owner'])}"
                if i.get("when_text"):
                    extra += f" — **{html.escape(i['when_text'])}**"
                if i.get("deadline"):
                    extra += f" (due: {html.escape(i['deadline'])})"
                field_text = html.escape(i.get(field) or "")
                st.markdown(f"`{format_ts(i.get('timestamp') or 0)}` "
                            f"{field_text}{extra}{flag}")
    minutes_path = meeting["dir"] / "minutes.md"
    if not minutes_path.exists():
        st.caption("Minutes not generated yet — run: marwin analyze")
    else:
        with st.expander("📝 Minutes of Meeting", expanded=False):
            st.markdown(minutes_path.read_text(encoding="utf-8"))
    st.divider()
else:
    st.caption("No intelligence yet — run: marwin analyze")

for seg in segments:
    st.markdown(_segment_html(seg), unsafe_allow_html=True)
