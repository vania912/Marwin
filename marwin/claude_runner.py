"""Headless Claude invocation — the ONLY approved text-analysis destination
(HARD RULE 2): Anthropic via the user's existing Claude plan, no new services."""
import json
import subprocess


class ClaudeError(RuntimeError):
    pass


def run_claude(prompt: str, timeout_s: int = 600) -> str:
    """Run `claude -p` with prompt on stdin.

    shell=True + stdin avoids Windows arg-quoting breakage; utf-8/replace
    because transcripts are bilingual (both live-proven 2026-07-10)."""
    try:
        result = subprocess.run(
            "claude -p", input=prompt, shell=True, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise ClaudeError(f"claude -p timed out after {timeout_s}s")
    except (FileNotFoundError, OSError) as e:
        raise ClaudeError(f"claude CLI not found — is Claude Code installed? ({e})")
    out = (result.stdout or "").strip()
    if result.returncode != 0 or not out:
        detail = (result.stderr or out or "empty output").strip()[:300]
        raise ClaudeError(f"claude -p failed (rc={result.returncode}): {detail}")
    return out


def extract_json(text: str):
    """Parse the first JSON array or object embedded in text."""
    starts = [(text.find(c), c) for c in "[{" if text.find(c) != -1]
    if not starts:
        raise ClaudeError(f"no JSON found in claude output: {text[:200]}")
    start, _open_c = min(starts)
    try:
        obj, _end = json.JSONDecoder().raw_decode(text[start:])
        return obj
    except json.JSONDecodeError as e:
        raise ClaudeError(f"invalid JSON from claude: {e}") from e
