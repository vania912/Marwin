"""The extraction agents — each one job, one headless Claude call.
Agents read the ENGLISH rendering (single language extracts better);
timestamps refer to the [Ns] markers in the rendered transcript."""
from .claude_runner import run_claude, extract_json, ClaudeError


def render_transcript(segments: list) -> str:
    lines = []
    for s in segments:
        text = s.get("english") or s["text"]
        lines.append(f"[{s['start']:.0f}s] {s['speaker']}: {text}")
    return "\n".join(lines)


_COMMON = """You are the {role} for a meeting-intelligence tool.
Meeting: "{title}" on {date}.
Rules: use ONLY what the transcript supports; timestamps are the [Ns] numbers of the supporting line; if nothing qualifies return an empty JSON array []; return RAW JSON only — no markdown, no commentary.

Transcript:
{transcript}

"""

AGENTS = {
    "tasks": {
        "kind": "array",
        "prompt": _COMMON.replace("{role}", "Action-Item extraction agent") + """Extract every action item / task someone is expected to do.
Return a JSON array of {"task": "<imperative description>", "owner": "<speaker label who must do it, or null>", "deadline": "<verbatim deadline words or null>", "timestamp": <N>, "quote": "<short supporting quote>"}.""",
    },
    "decisions": {
        "kind": "array",
        "prompt": _COMMON.replace("{role}", "Decision extraction agent") + """Extract every decision that was made (a choice settled, not merely discussed).
Return a JSON array of {"decision": "<what was decided>", "decided_by": "<speaker label or null>", "timestamp": <N>, "quote": "<short supporting quote>"}.""",
    },
    "questions": {
        "kind": "array",
        "prompt": _COMMON.replace("{role}", "Open-Question extraction agent") + """Extract questions that were asked. Mark whether the transcript shows them answered.
Return a JSON array of {"question": "<the question>", "asked_by": "<speaker label>", "answered": <true|false>, "timestamp": <N>}.""",
    },
    "risks": {
        "kind": "array",
        "prompt": _COMMON.replace("{role}", "Risk extraction agent") + """Extract concerns, blockers, or risks raised.
Return a JSON array of {"risk": "<the concern>", "raised_by": "<speaker label>", "severity": "<low|medium|high>", "timestamp": <N>}.""",
    },
    "deadlines": {
        "kind": "array",
        "prompt": _COMMON.replace("{role}", "Deadline extraction agent") + """Extract every date/time commitment (deadlines, due times, scheduled follow-ups).
Return a JSON array of {"what": "<what is due>", "when_text": "<verbatim time words, e.g. 'by Friday noon'>", "when_iso": "<ISO date/time if derivable, else null>", "owner": "<speaker label or null>", "timestamp": <N>}.""",
    },
    "topics": {
        "kind": "array",
        "prompt": _COMMON.replace("{role}", "Topic segmentation agent") + """Split the meeting into topic chapters.
Return a JSON array of {"topic": "<short title>", "start": <N of first line>, "end": <N of last line>}.""",
    },
    "summary": {
        "kind": "object",
        "prompt": _COMMON.replace("{role}", "Minutes summary agent") + """Write concise meeting minutes in ENGLISH.
Return a JSON object {"overview": "<2-4 sentence overview>", "by_topic": [{"topic": "<title>", "notes": ["<concise bullet 1>", "<concise bullet 2>", "..."]}], "outcomes": "<1-3 sentences on outcomes/next steps>"}.
For "notes": write each note as one concise bullet point (not a paragraph); bold key terms, tool names, numbers, and times with **double asterisks**.
Never include transcript timestamps or [Ns] markers in any text — plain prose only.""",
    },
}


def _fill(template: str, transcript_text: str, meta: dict) -> str:
    return (template.replace("{title}", str(meta.get("title", "meeting")))
                    .replace("{date}", str(meta.get("date", "")))
                    .replace("{transcript}", transcript_text))


# The one PRIMARY text key each agent's schema requires; other fields are
# optional and are left unchecked here.
REQUIRED_KEY = {
    "tasks": "task",
    "decisions": "decision",
    "questions": "question",
    "risks": "risk",
    "deadlines": "what",
    "topics": "topic",
    "summary": "overview",
}


def _shape_error(name: str, result, want_list: bool):
    """Return a short description of what's wrong with `result`, or None
    if it is well-shaped. Checked: top-level kind, then (for array agents)
    every element is a dict with the required key non-None, or (for object
    agents) the object itself has the required key non-None."""
    if isinstance(result, list) != want_list:
        return f"expected {'array' if want_list else 'object'}"
    key = REQUIRED_KEY[name]
    if want_list:
        for idx, item in enumerate(result):
            if not isinstance(item, dict):
                return f"element {idx} is not a JSON object"
            if item.get(key) is None:
                return f"element {idx} is missing required key '{key}'"
        return None
    if result.get(key) is None:
        return f"missing required key '{key}'"
    return None


def run_agent(name: str, transcript_text: str, meta: dict, run=run_claude):
    spec = AGENTS[name]
    prompt = _fill(spec["prompt"], transcript_text, meta)
    want_list = spec["kind"] == "array"
    error = None
    for attempt in (1, 2):
        reply = run(prompt)  # a CLI failure here propagates immediately, no retry
        try:
            result = extract_json(reply)
        except ClaudeError as e:
            error = f"could not parse JSON ({e})"
        else:
            error = _shape_error(name, result, want_list)
            if error is None:
                return result
        if attempt == 1:
            prompt += f"\nIMPORTANT: {error}. Fix and return RAW JSON only."
    raise ClaudeError(f"agent {name}: {error} after retry")


QA_PROMPT = """You are the QA agent. For each numbered claim below, score 0-100 how directly the transcript supports it (100 = explicitly stated; 0 = unsupported), with a short reason.
Return RAW JSON only: a JSON array of {"id": "<id>", "score": <0-100>, "reason": "<short>"}.

Transcript:
{transcript}

Claims:
{claims}
"""


def score_items(numbered_items: list, transcript_text: str, run=run_claude) -> dict:
    import json as _json
    claims = _json.dumps(numbered_items, ensure_ascii=False, indent=0)
    prompt = (QA_PROMPT.replace("{transcript}", transcript_text)
                       .replace("{claims}", claims))
    result = extract_json(run(prompt))
    if not isinstance(result, list):
        raise ClaudeError("QA agent: expected array")
    scores = {}
    for r in result:
        if not isinstance(r, dict) or "id" not in r:
            continue  # skip non-dict / id-less elements rather than raising
        try:
            score = int(float(r.get("score", 0)))
        except (TypeError, ValueError):
            continue  # skip elements with an uncoercible score
        scores[str(r["id"])] = {"score": score, "reason": str(r.get("reason", ""))}
    return scores
