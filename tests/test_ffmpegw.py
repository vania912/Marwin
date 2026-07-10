import shutil
import wave
import pytest
from marwin.ffmpegw import join_cmd, join_to_stereo_opus, probe_duration

def test_join_cmd_structure(tmp_path):
    cmd = join_cmd(tmp_path / "mic.wav", tmp_path / "loop.wav",
                   tmp_path / "audio.opus")
    assert cmd[0] == "ffmpeg"
    joined = " ".join(cmd)
    assert "libopus" in joined and "64k" in joined
    # mic listed first => joins as left channel
    assert cmd.index(str(tmp_path / "mic.wav")) < cmd.index(str(tmp_path / "loop.wav"))

ffmpeg_missing = shutil.which("ffmpeg") is None

@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not installed")
def test_join_and_probe_roundtrip(tmp_path):
    for name in ("mic.wav", "loop.wav"):
        with wave.open(str(tmp_path / name), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            wf.writeframes(b"\x00\x01" * 16000 * 2)  # 2 seconds
    out = tmp_path / "audio.opus"
    join_to_stereo_opus(tmp_path / "mic.wav", tmp_path / "loop.wav", out)
    assert out.exists() and out.stat().st_size > 0
    assert abs(probe_duration(out) - 2.0) < 0.5
