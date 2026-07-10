"""Speaker assignment + language detection.

Pure stdlib: this file is uploaded to Kaggle with the audio and imported
by the kernel, so it must not import anything outside the stdlib."""
import math


def detect_lang(text: str) -> str:
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return "en"
    # Arabic script = Urdu; Devanagari = Hindustani that Whisper wrote in
    # Hindi script (observed live 2026-07-10 on Urdu speech) — tag both "ur".
    urdu_ish = sum(1 for c in alpha
                   if "؀" <= c <= "ۿ" or "ऀ" <= c <= "ॿ")
    return "ur" if urdu_ish / len(alpha) > 0.20 else "en"


def channel_energy(rms: list[float], hop: float, start: float, end: float) -> float:
    lo = max(0, int(start / hop))
    hi = min(len(rms), math.ceil(end / hop))
    window = rms[lo:hi]
    return sum(window) / len(window) if window else 0.0


def dominant_turn(turns: list[dict], start: float, end: float) -> str | None:
    overlaps: dict[str, float] = {}
    for t in turns:
        ov = min(end, t["end"]) - max(start, t["start"])
        if ov > 0:
            overlaps[t["speaker"]] = overlaps.get(t["speaker"], 0.0) + ov
    return max(overlaps, key=overlaps.get) if overlaps else None


MIC_DOMINANCE = 1.2


def assign_speakers(wsegs: list[dict], turns: list[dict],
                    mic_rms: list[float], loop_rms: list[float],
                    hop: float = 0.5, mic_label: str = "Me") -> list[dict]:
    out = []
    for seg in wsegs:
        mic_e = channel_energy(mic_rms, hop, seg["start"], seg["end"])
        loop_e = channel_energy(loop_rms, hop, seg["start"], seg["end"])
        if mic_e > 0 and mic_e >= loop_e * MIC_DOMINANCE:
            speaker = mic_label
        else:
            speaker = dominant_turn(turns, seg["start"], seg["end"]) or "Unknown"
        out.append({**seg, "speaker": speaker, "lang": detect_lang(seg["text"])})
    return out
