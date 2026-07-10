import struct
import threading
from pathlib import Path

from .chunks import ChunkWriter, stitch, list_chunks
from .ffmpegw import join_to_stereo_opus, probe_duration
from .meetings import update_meta

FRAMES_PER_READ = 1024

# A hardware-muted mic delivers pure digital silence (observed peak <= 4);
# any live mic picks up ambient noise well above this.
MIC_SILENCE_PEAK = 100


def mic_looks_muted(peak: int) -> bool:
    return peak < MIC_SILENCE_PEAK


def mic_peak(seconds: float = 2.5, audio_factory=None) -> int:
    """Sample the default microphone and return the absolute sample peak.

    Used as a pre-flight gate: some laptops mute the mic in hardware via
    an F4 key, which silently records nothing (live incident 2026-07-10)."""
    if audio_factory is None:
        import pyaudiowpatch as pyaudio
        audio_factory = pyaudio.PyAudio
    import pyaudiowpatch as pyaudio
    p = audio_factory()
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        mic = p.get_device_info_by_index(wasapi["defaultInputDevice"])
        stream, _channels, rate = _open_stream(p, mic)
        peak = 0
        for _ in range(max(1, int(rate / FRAMES_PER_READ * seconds))):
            data = stream.read(FRAMES_PER_READ, exception_on_overflow=False)
            n = len(data) // 2
            if n:
                peak = max(peak, max(abs(s) for s in
                                     struct.unpack(f"<{n}h", data)))
        stream.stop_stream()
        stream.close()
        return peak
    finally:
        p.terminate()


def capture_loop(read_fn, writer: ChunkWriter, stop_event: threading.Event) -> None:
    try:
        while not stop_event.is_set():
            writer.write(read_fn())
    finally:
        writer.close()


def _default_render_device(p) -> dict:
    """Return the default WASAPI render (speakers/headset) device info."""
    import pyaudiowpatch as pyaudio
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    return p.get_device_info_by_index(wasapi["defaultOutputDevice"])


def find_devices(p):
    """Return (mic_device, loopback_device) info dicts.

    Requires pyaudiowpatch: the loopback device mirrors the default
    output (speakers/headset) so we capture what the user hears."""
    import pyaudiowpatch as pyaudio
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    speakers = _default_render_device(p)
    loopback = None
    if speakers.get("isLoopbackDevice"):
        loopback = speakers
    else:
        for dev in p.get_loopback_device_info_generator():
            if speakers["name"] in dev["name"]:
                loopback = dev
                break
    if loopback is None:
        raise RuntimeError("No WASAPI loopback device found — is audio output active?")
    mic = p.get_device_info_by_index(wasapi["defaultInputDevice"])
    return mic, loopback


def _open_stream(p, device: dict):
    import pyaudiowpatch as pyaudio
    channels = max(1, int(device["maxInputChannels"]))
    rate = int(device["defaultSampleRate"])
    stream = p.open(format=pyaudio.paInt16, channels=channels, rate=rate,
                    input=True, input_device_index=device["index"],
                    frames_per_buffer=FRAMES_PER_READ)
    return stream, channels, rate


def _silence_keepalive(p, device: dict, stop_event: threading.Event) -> None:
    """Play zeros on the render device until stop_event is set.

    WASAPI loopback only delivers frames while the render device has an
    active audio session; without one, the loopback stream's read()
    blocks indefinitely (e.g. when recording continues after meeting
    audio stops, or through a quiet stretch) and the two channels drift
    out of time-alignment. Writing real zeros keeps the device clocked
    so silence stays silence on the timeline. Keepalive failure must
    never kill a recording, so any exception is reduced to a warning."""
    try:
        import pyaudiowpatch as pyaudio
        stream = p.open(format=pyaudio.paInt16, channels=1,
                        rate=int(device["defaultSampleRate"]), output=True,
                        output_device_index=device["index"],
                        frames_per_buffer=1024)
        try:
            while not stop_event.is_set():
                stream.write(b"\x00\x00" * 1024)
        finally:
            stream.close()
    except Exception as exc:
        print(f"warning: silence keepalive failed: {exc}")


def _capture_target(name: str, read_fn, writer: ChunkWriter,
                    stop_event: threading.Event,
                    errors: list[tuple[str, Exception]]) -> None:
    """Thread target: run capture_loop, recording any failure by name."""
    try:
        capture_loop(read_fn, writer, stop_event)
    except Exception as exc:
        errors.append((name, exc))


def _shutdown_capture(threads: list[tuple[str, threading.Thread]],
                      streams: list[tuple[str, object]],
                      errors: list[tuple[str, Exception]]) -> None:
    """Join capture threads, then close streams whose thread has exited.

    A stream whose thread is still alive after the join timeout is left
    open — closing it mid-read is a cross-thread race."""
    stuck = set()
    for name, t in threads:
        t.join(timeout=5)
        if t.is_alive():
            print(f"warning: {name} capture thread did not stop cleanly")
            stuck.add(name)
    for name, stream in streams:
        if name in stuck:
            continue
        stream.stop_stream()
        stream.close()
    for name, exc in errors:
        print(f"warning: {name} capture failed: {exc}")


def record_meeting(meeting_dir: Path, cfg: dict,
                   stop_event: threading.Event, audio_factory=None) -> Path:
    """Record mic + loopback into chunked WAVs until stop_event, then
    finalize to audio.opus. audio_factory is injectable for tests."""
    if audio_factory is None:
        import pyaudiowpatch as pyaudio
        audio_factory = pyaudio.PyAudio
    p = audio_factory()
    chunk_seconds = cfg["recording"]["chunk_seconds"]
    threads: list[tuple[str, threading.Thread]] = []
    streams: list[tuple[str, object]] = []
    errors: list[tuple[str, Exception]] = []
    keepalive_stop = threading.Event()
    keepalive = None
    try:
        # Keepalive starts before any capture stream opens and (see the
        # finally below) outlives the final loopback reads, so the render
        # session is active for the whole recording.
        keepalive = threading.Thread(
            target=_silence_keepalive,
            args=(p, _default_render_device(p), keepalive_stop), daemon=True)
        keepalive.start()
        mic_dev, loop_dev = find_devices(p)
        try:
            for name, dev in (("mic", mic_dev), ("loop", loop_dev)):
                stream, channels, rate = _open_stream(p, dev)
                streams.append((name, stream))
                writer = ChunkWriter(meeting_dir, name, rate, channels, 2,
                                     chunk_seconds)
                read_fn = (lambda s: lambda: s.read(FRAMES_PER_READ,
                           exception_on_overflow=False))(stream)
                t = threading.Thread(
                    target=_capture_target,
                    args=(name, read_fn, writer, stop_event, errors),
                    daemon=True)
                t.start()
                threads.append((name, t))
            stop_event.wait()
        except BaseException:
            stop_event.set()
            _shutdown_capture(threads, streams, errors)
            raise
        _shutdown_capture(threads, streams, errors)
    finally:
        # Stop the keepalive only after the capture threads have been
        # joined and their streams closed (both the normal path and the
        # partial-failure path run _shutdown_capture before this block).
        keepalive_stop.set()
        if keepalive is not None:
            keepalive.join(timeout=5)
        p.terminate()
    return finalize_recording(meeting_dir)


def finalize_recording(meeting_dir: Path) -> Path:
    meeting_dir = Path(meeting_dir)
    mic_wav = stitch(meeting_dir, "mic", meeting_dir / "mic.wav")
    loop_wav = stitch(meeting_dir, "loop", meeting_dir / "loop.wav")
    out = meeting_dir / "audio.opus"
    join_to_stereo_opus(mic_wav, loop_wav, out)
    update_meta(meeting_dir, duration_s=round(probe_duration(out), 1))
    for wav in [mic_wav, loop_wav, *list_chunks(meeting_dir, "mic"),
                *list_chunks(meeting_dir, "loop")]:
        wav.unlink()
    return out
