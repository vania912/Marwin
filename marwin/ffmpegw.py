import shutil
import subprocess
from pathlib import Path


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise RuntimeError(
                f"{tool} not found — install with: winget install ffmpeg")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{cmd[0]} failed (rc={result.returncode}): {result.stderr[-500:]}")
    return result


def join_cmd(mic_wav: Path, loop_wav: Path, out_opus: Path) -> list[str]:
    fc = ("[0:a]aformat=sample_rates=16000:channel_layouts=mono[l];"
          "[1:a]aformat=sample_rates=16000:channel_layouts=mono[r];"
          "[l][r]join=inputs=2:channel_layout=stereo[a]")
    return ["ffmpeg", "-y", "-i", str(mic_wav), "-i", str(loop_wav),
            "-filter_complex", fc, "-map", "[a]",
            "-c:a", "libopus", "-b:a", "64k", str(out_opus)]


def join_to_stereo_opus(mic_wav: Path, loop_wav: Path, out_opus: Path) -> None:
    _run(join_cmd(mic_wav, loop_wav, out_opus))


def probe_duration(path: Path) -> float:
    result = _run(["ffprobe", "-v", "error", "-show_entries",
                   "format=duration", "-of", "csv=p=0", str(path)])
    return float(result.stdout.strip())
