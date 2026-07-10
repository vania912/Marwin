import re
import wave
from pathlib import Path


class ChunkWriter:
    """Writes audio frames to numbered WAV chunks, rotating every
    chunk_seconds so a crash loses at most one chunk of audio."""

    def __init__(self, directory: Path, name: str, framerate: int,
                 channels: int, sampwidth: int, chunk_seconds: int):
        self.directory = Path(directory)
        self.name = name
        self.framerate = framerate
        self.channels = channels
        self.sampwidth = sampwidth
        self.frames_per_chunk = chunk_seconds * framerate
        self._index = 0
        self._frames_in_current = 0
        self._wf = None

    def _open_next(self):
        self._index += 1
        path = self.directory / f"{self.name}-{self._index:04d}.wav"
        self._wf = wave.open(str(path), "wb")
        self._wf.setnchannels(self.channels)
        self._wf.setsampwidth(self.sampwidth)
        self._wf.setframerate(self.framerate)
        self._frames_in_current = 0

    def write(self, data: bytes):
        if self._wf is None or self._frames_in_current >= self.frames_per_chunk:
            if self._wf is not None:
                self._wf.close()
            self._open_next()
        self._wf.writeframes(data)
        self._frames_in_current += len(data) // (self.sampwidth * self.channels)

    def close(self):
        if self._wf is not None:
            self._wf.close()
            self._wf = None


def list_chunks(directory: Path, name: str) -> list[Path]:
    return sorted(Path(directory).glob(f"{name}-[0-9][0-9][0-9][0-9].wav"))


def has_chunks(directory: Path) -> bool:
    return any(re.match(r".+-\d{4}\.wav$", p.name)
               for p in Path(directory).glob("*.wav"))


def stitch(directory: Path, name: str, out_path: Path) -> Path:
    chunk_files = list_chunks(directory, name)
    if not chunk_files:
        raise FileNotFoundError(f"no chunks named {name}-NNNN.wav in {directory}")
    with wave.open(str(chunk_files[0]), "rb") as first:
        params = first.getparams()
    with wave.open(str(out_path), "wb") as out:
        out.setparams(params)
        for cf in chunk_files:
            with wave.open(str(cf), "rb") as wf:
                if wf.getparams()[:3] != params[:3]:
                    raise ValueError(f"chunk {cf.name} has mismatched format")
                out.writeframes(wf.readframes(wf.getnframes()))
    return Path(out_path)
