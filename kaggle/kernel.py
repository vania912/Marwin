"""Marwin processing kernel — runs on Kaggle GPU.
Input:  the attached marwin-inbox dataset {audio.opus, merge.py, transcript.py}
Output: /kaggle/working/transcript.json
"""
import glob
import json
import math
import os
import subprocess
import sys
import wave


def _find_inbox() -> str:
    """Locate the attached dataset regardless of mount naming — Kaggle's
    mount path conventions vary; searching is robust and self-diagnosing."""
    hits = glob.glob("/kaggle/input/**/merge.py", recursive=True)
    if not hits:
        print("DEBUG: merge.py not found. /kaggle/input tree:")
        for root, _dirs, files in os.walk("/kaggle/input"):
            for f in files:
                print(" ", os.path.join(root, f))
        raise SystemExit("marwin-inbox dataset not mounted or incomplete")
    return os.path.dirname(hits[0])


INBOX = _find_inbox()
WORK = "/kaggle/working"
sys.path.insert(0, INBOX)  # merge.py, transcript.py travel with the audio
print(f"inbox mounted at: {INBOX}")

os.system("pip install -q faster-whisper pyannote.audio jsonschema")

import merge  # noqa: E402
import transcript as transcript_mod  # noqa: E402


def sh(cmd: str):
    subprocess.run(cmd, shell=True, check=True)


def rms_per_hop(wav_path: str, hop: float = 0.5) -> list[float]:
    import numpy as np
    with wave.open(wav_path, "rb") as wf:
        rate = wf.getframerate()
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    data = data.astype(np.float64) / 32768.0
    hop_n = int(rate * hop)
    return [float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
            for chunk in (data[i:i + hop_n]
                          for i in range(0, len(data), hop_n))]


def main():
    audio = f"{INBOX}/audio.opus"
    # Split stereo: L = mic (you), R = loopback (everyone else)
    sh(f'ffmpeg -y -i {audio} -filter_complex '
       f'"[0:a]channelsplit=channel_layout=stereo[l][r]" '
       f'-map "[l]" -ar 16000 {WORK}/mic.wav '
       f'-map "[r]" -ar 16000 {WORK}/loop.wav')
    sh(f"ffmpeg -y -i {audio} -ac 1 -ar 16000 {WORK}/mix.wav")

    # --- Whisper large-v3 on the mixdown ---
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    except ValueError:
        # Older GPUs (e.g. Kaggle P100, observed live 2026-07-10) lack
        # efficient float16; let ctranslate2 pick the best supported type.
        print("float16 unsupported on this GPU; using compute_type=auto")
        model = WhisperModel("large-v3", device="cuda", compute_type="auto")
    segments_iter, info = model.transcribe(f"{WORK}/mix.wav",
                                           language=None, vad_filter=True)
    # HARD RULE: meetings are English + Urdu only.
    # Whisper hears Urdu as Hindi and writes Devanagari; if it detects
    # anything outside {en, ur}, retranscribe forcing Urdu.
    if info.language not in ("en", "ur"):
        print(f"detected '{info.language}' — outside en/ur, forcing ur")
        segments_iter, info = model.transcribe(f"{WORK}/mix.wav",
                                               language="ur", vad_filter=True)
    wsegs = [{"start": round(s.start, 2), "end": round(s.end, 2),
              "text": s.text.strip(),
              "confidence": round(max(0.0, min(1.0, math.exp(s.avg_logprob))), 3)}
             for s in segments_iter if s.text.strip()]

    # --- Diarization on loopback only ---
    token_file = os.path.join(INBOX, "hf_token.txt")
    if os.path.exists(token_file):
        with open(token_file) as tf:
            hf_token = tf.read().strip()
    else:
        # Fallback: works only for interactively-run kernels — the secrets
        # service rejects API-pushed kernels (observed live 2026-07-10).
        from kaggle_secrets import UserSecretsClient
        hf_token = UserSecretsClient().get_secret("HF_TOKEN")
    from pyannote.audio import Pipeline, Model, Inference
    from pyannote.core import Segment

    def from_pretrained(cls, name):
        # pyannote 4.x renamed use_auth_token= to token= (observed live
        # 2026-07-10); support both so unpinned installs keep working.
        try:
            return cls.from_pretrained(name, token=hf_token)
        except TypeError:
            return cls.from_pretrained(name, use_auth_token=hf_token)

    pipeline = from_pretrained(Pipeline, "pyannote/speaker-diarization-3.1")
    import torch
    pipeline.to(torch.device("cuda"))
    result = pipeline(f"{WORK}/loop.wav")
    # pyannote 4.x wraps the annotation in a DiarizeOutput dataclass
    # (observed live 2026-07-10); 3.x returns the Annotation directly.
    diarization = getattr(result, "speaker_diarization", result)
    turns = [{"start": round(turn.start, 2), "end": round(turn.end, 2),
              "speaker": spk}
             for turn, _, spk in diarization.itertracks(yield_label=True)]

    # --- Speaker embeddings (up to 3 longest turns per speaker, >=1s) ---
    emb_model = from_pretrained(Model, "pyannote/embedding")
    inference = Inference(emb_model, window="whole")
    by_speaker: dict[str, list] = {}
    for t in turns:
        by_speaker.setdefault(t["speaker"], []).append(t)
    speakers = []
    for spk, ts in by_speaker.items():
        long_turns = sorted((t for t in ts if t["end"] - t["start"] >= 1.0),
                            key=lambda t: t["end"] - t["start"], reverse=True)[:3]
        vecs = [inference.crop(f"{WORK}/loop.wav", Segment(t["start"], t["end"]))
                for t in long_turns]
        if vecs:
            import numpy as np
            centroid = np.mean(np.stack(vecs), axis=0).tolist()
            speakers.append({"label": spk, "embedding": centroid})

    # --- Merge + save ---
    mic_rms = rms_per_hop(f"{WORK}/mic.wav")
    loop_rms = rms_per_hop(f"{WORK}/loop.wav")
    label_file = os.path.join(INBOX, "mic_label.txt")
    if os.path.exists(label_file):
        with open(label_file, encoding="utf-8") as lf:
            mic_label = lf.read().strip() or "Me"
    else:
        mic_label = "Me"
    segments = merge.assign_speakers(wsegs, turns, mic_rms, loop_rms,
                                     mic_label=mic_label)
    data = {
        "duration": round(float(info.duration), 1),
        "model_info": {"whisper": "large-v3",
                       "diarization": "pyannote/speaker-diarization-3.1",
                       "detected_language": info.language},
        "speakers": speakers,
        "segments": segments,
    }
    transcript_mod.save(f"{WORK}/transcript.json", data)
    # Everything left in /kaggle/working gets downloaded by `kernels
    # output` — remove work WAVs (~350MB/hour) so only the transcript ships.
    for wav in ("mic.wav", "loop.wav", "mix.wav"):
        try:
            os.remove(f"{WORK}/{wav}")
        except OSError:
            pass
    print(f"OK: {len(segments)} segments, {len(speakers)} loopback speakers")


if __name__ == "__main__":
    main()
