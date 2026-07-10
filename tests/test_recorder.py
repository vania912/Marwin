import json
import threading
import time
import wave
from pathlib import Path
import pytest

from marwin.recorder import capture_loop, finalize_recording, record_meeting
from marwin.chunks import ChunkWriter

RATE = 16000
FRAME = b"\x00\x01" * 512  # one 512-frame read, mono 16-bit


def test_capture_loop_writes_until_stopped(tmp_path):
    writer = ChunkWriter(tmp_path, "mic", RATE, 1, 2, chunk_seconds=60)
    stop = threading.Event()
    reads = {"n": 0}

    def read_fn():
        reads["n"] += 1
        if reads["n"] >= 10:
            stop.set()
        return FRAME

    capture_loop(read_fn, writer, stop)
    chunk = tmp_path / "mic-0001.wav"
    assert chunk.exists()
    with wave.open(str(chunk), "rb") as wf:
        assert wf.getnframes() == 10 * 512


def _write_chunks(d: Path, name: str, seconds: int):
    w = ChunkWriter(d, name, RATE, 1, 2, chunk_seconds=2)
    for _ in range(seconds):
        w.write(b"\x00\x01" * RATE)
    w.close()


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None,
                    reason="ffmpeg not installed")
def test_finalize_recording(tmp_path):
    (tmp_path / "meta.json").write_text(
        json.dumps({"title": "t", "date": "2026-07-09", "duration_s": None}))
    _write_chunks(tmp_path, "mic", 3)
    _write_chunks(tmp_path, "loop", 3)
    opus = finalize_recording(tmp_path)
    assert opus == tmp_path / "audio.opus"
    assert opus.exists()
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert 2.5 < meta["duration_s"] < 3.5
    assert not list(tmp_path.glob("*.wav"))  # intermediates cleaned up


class _FakeStream:
    def __init__(self, on_read=None, events=None, label="input"):
        self.stopped = False
        self.closed = False
        self.reads = 0
        self._on_read = on_read
        self._events = events
        self._label = label

    def read(self, n, exception_on_overflow=False):
        self.reads += 1
        if self._on_read is not None:
            self._on_read()
        time.sleep(0.001)  # pace like a real device so data stays small
        return b"\x00\x00" * n  # silence, mono 16-bit

    def stop_stream(self):
        self.stopped = True

    def close(self):
        self.closed = True
        if self._events is not None:
            self._events.append(f"close:{self._label}")


class _FakeOutputStream:
    """Fake render stream handed to the silence keepalive."""

    def __init__(self, events=None):
        self.writes = 0
        self.closed = False
        self._events = events

    def write(self, data):
        self.writes += 1
        time.sleep(0.001)  # pace like a real device

    def close(self):
        self.closed = True
        if self._events is not None:
            self._events.append("close:keepalive")


class _FakePyAudio:
    """Output opens (silence keepalive) always succeed. Input opens:
    first succeeds; the second raises RuntimeError unless
    fail_second_input=False."""

    _speakers = {"index": 0, "name": "Speakers", "isLoopbackDevice": True,
                 "maxInputChannels": 2, "defaultSampleRate": 16000.0}
    _mic = {"index": 1, "name": "Mic", "maxInputChannels": 1,
            "defaultSampleRate": 16000.0}

    def __init__(self, fail_second_input=True):
        self.streams = []
        self.output_streams = []
        self.terminated = False
        self.fail_second_input = fail_second_input
        self.on_input_read = None
        self.events: list[str] = []  # ordered log of stream close() calls

    def get_host_api_info_by_type(self, api_type):
        return {"defaultOutputDevice": 0, "defaultInputDevice": 1}

    def get_device_info_by_index(self, index):
        return {0: self._speakers, 1: self._mic}[index]

    def open(self, **kwargs):
        if kwargs.get("output"):
            stream = _FakeOutputStream(events=self.events)
            self.output_streams.append(stream)
            return stream
        if self.streams and self.fail_second_input:
            raise RuntimeError("no device")
        stream = _FakeStream(on_read=self.on_input_read, events=self.events,
                             label=f"input:{len(self.streams) + 1}")
        self.streams.append(stream)
        return stream

    def terminate(self):
        self.terminated = True


def test_record_meeting_cleans_up_on_partial_start_failure(tmp_path):
    p = _FakePyAudio()
    cfg = {"recording": {"chunk_seconds": 60}}
    stop = threading.Event()

    with pytest.raises(RuntimeError, match="no device"):
        record_meeting(tmp_path, cfg, stop, audio_factory=lambda: p)

    assert p.terminated
    (mic_stream,) = p.streams
    assert mic_stream.stopped
    assert mic_stream.closed


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None,
                    reason="ffmpeg not installed")
def test_record_meeting_starts_silence_keepalive(tmp_path):
    (tmp_path / "meta.json").write_text(
        json.dumps({"title": "t", "date": "2026-07-09", "duration_s": None}))
    p = _FakePyAudio(fail_second_input=False)
    cfg = {"recording": {"chunk_seconds": 60}}
    stop = threading.Event()
    safety = threading.Timer(5.0, stop.set)  # fail, don't hang, if gate never fires

    def reads_gate():
        # Stop once the keepalive has written silence and each capture
        # stream has produced at least one chunk-worth of reads.
        if (p.output_streams and p.output_streams[0].writes
                and len(p.streams) == 2 and all(s.reads for s in p.streams)):
            stop.set()

    p.on_input_read = reads_gate
    safety.start()
    try:
        opus = record_meeting(tmp_path, cfg, stop, audio_factory=lambda: p)
    finally:
        safety.cancel()

    assert opus.exists()
    (out,) = p.output_streams  # keepalive opened exactly one render stream
    assert out.writes > 0
    assert out.closed

    # Ordering guarantee: the keepalive must outlive the final loopback
    # reads, so its stream closes only AFTER every capture stream closed.
    events = p.events
    assert "close:keepalive" in events
    input_closes = [i for i, e in enumerate(events)
                    if e.startswith("close:input")]
    assert len(input_closes) == 2  # both capture streams were closed
    assert events.index("close:keepalive") > max(input_closes)


class _FakePreflightStream:
    def __init__(self, sample: int):
        self._sample = sample

    def read(self, n, exception_on_overflow=False):
        import struct as _struct
        return _struct.pack(f"<{n}h", *([self._sample] * n))

    def stop_stream(self):
        pass

    def close(self):
        pass


class _FakePreflightAudio:
    def __init__(self, sample: int):
        self._sample = sample

    def get_host_api_info_by_type(self, t):
        return {"defaultInputDevice": 0}

    def get_device_info_by_index(self, i):
        return {"index": 0, "maxInputChannels": 1, "defaultSampleRate": 16000}

    def open(self, **kwargs):
        return _FakePreflightStream(self._sample)

    def terminate(self):
        pass


def test_mic_peak_detects_silence_and_signal():
    from marwin.recorder import mic_peak, mic_looks_muted
    silent = mic_peak(seconds=0.1, audio_factory=lambda: _FakePreflightAudio(0))
    loud = mic_peak(seconds=0.1, audio_factory=lambda: _FakePreflightAudio(5000))
    assert mic_looks_muted(silent) is True
    assert mic_looks_muted(loud) is False
