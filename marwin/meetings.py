import datetime as dt
import json
import re
from pathlib import Path


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return slug.strip("-")


def create_meeting_dir(meetings_root: Path, title: str,
                       date: dt.date | None = None) -> Path:
    date = date or dt.date.today()
    base = f"{date.isoformat()}-{slugify(title)}"
    meetings_root = Path(meetings_root)
    candidate = meetings_root / base
    n = 2
    while candidate.exists():
        candidate = meetings_root / f"{base}-{n}"
        n += 1
    candidate.mkdir(parents=True)
    meta = {"title": title, "date": date.isoformat(), "duration_s": None,
            "started_at": dt.datetime.now().isoformat(timespec="seconds")}
    (candidate / "meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")
    return candidate


def read_meta(meeting_dir: Path) -> dict:
    return json.loads((Path(meeting_dir) / "meta.json").read_text(encoding="utf-8"))


def update_meta(meeting_dir: Path, **fields) -> dict:
    meta = read_meta(meeting_dir)
    meta.update(fields)
    (Path(meeting_dir) / "meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def list_meetings(meetings_root: Path) -> list[dict]:
    meetings_root = Path(meetings_root)
    out = []
    if not meetings_root.exists():
        return out
    for d in sorted(meetings_root.iterdir(), reverse=True):
        if not (d / "meta.json").exists():
            continue
        meta = read_meta(d)
        out.append({
            "dir": d,
            "title": meta["title"],
            "date": meta["date"],
            "duration_s": meta.get("duration_s"),
            "has_transcript": (d / "transcript.json").exists(),
        })
    return out


def latest_unprocessed(meetings_root: Path) -> Path | None:
    for m in list_meetings(meetings_root):
        if (m["dir"] / "audio.opus").exists() and not m["has_transcript"]:
            return m["dir"]
    return None


def latest_unanalyzed(meetings_root: Path) -> Path | None:
    for m in list_meetings(meetings_root):
        if (m["dir"] / "transcript.json").exists() \
                and not (m["dir"] / "intelligence.json").exists():
            return m["dir"]
    return None
