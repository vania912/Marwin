import wave
from marwin.chunks import ChunkWriter, list_chunks, stitch, has_chunks

RATE, CH, SW = 16000, 1, 2  # 16kHz mono 16-bit
ONE_SEC = b"\x00\x01" * RATE  # 1 second of frames


def write_seconds(tmp_path, name, seconds, chunk_seconds=2):
    w = ChunkWriter(tmp_path, name, RATE, CH, SW, chunk_seconds)
    for _ in range(seconds):
        w.write(ONE_SEC)
    w.close()
    return w


def test_rotation(tmp_path):
    write_seconds(tmp_path, "mic", 5, chunk_seconds=2)
    files = list_chunks(tmp_path, "mic")
    assert [f.name for f in files] == ["mic-0001.wav", "mic-0002.wav", "mic-0003.wav"]


def test_stitch_preserves_all_frames(tmp_path):
    write_seconds(tmp_path, "mic", 5, chunk_seconds=2)
    out = stitch(tmp_path, "mic", tmp_path / "mic.wav")
    with wave.open(str(out), "rb") as wf:
        assert wf.getnframes() == 5 * RATE
        assert wf.getframerate() == RATE


def test_has_chunks(tmp_path):
    assert has_chunks(tmp_path) is False
    write_seconds(tmp_path, "mic", 1)
    assert has_chunks(tmp_path) is True
