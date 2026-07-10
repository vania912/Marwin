import json
from pathlib import Path
import pytest
from marwin import kaggle_runner as kr


def test_stage_dataset_copies_code_and_audio(tmp_path):
    meeting = tmp_path / "m"; meeting.mkdir()
    (meeting / "audio.opus").write_bytes(b"opus")
    root = tmp_path / "proj"
    (root / "marwin").mkdir(parents=True)
    (root / "marwin" / "merge.py").write_text("# merge")
    (root / "marwin" / "transcript.py").write_text("# transcript")
    staging = kr.stage_dataset(tmp_path / "stage", meeting, root, "vania", "marwin-inbox")
    assert (staging / "audio.opus").read_bytes() == b"opus"
    assert (staging / "merge.py").exists()
    assert (staging / "transcript.py").exists()
    meta = json.loads((staging / "dataset-metadata.json").read_text())
    assert meta["id"] == "vania/marwin-inbox"
    assert not (staging / "hf_token.txt").exists()  # absent when not configured
    assert not (staging / "mic_label.txt").exists()


def test_stage_dataset_ships_hf_token_when_present(tmp_path):
    # Kaggle user secrets are not available to API-pushed kernels (HTTP 400,
    # observed live 2026-07-10); the token travels in the private dataset.
    meeting = tmp_path / "m"; meeting.mkdir()
    (meeting / "audio.opus").write_bytes(b"opus")
    root = tmp_path / "proj"
    (root / "marwin").mkdir(parents=True)
    (root / "marwin" / "merge.py").write_text("# merge")
    (root / "marwin" / "transcript.py").write_text("# transcript")
    (root / "hf_token.txt").write_text("hf_secret123\n")
    staging = kr.stage_dataset(tmp_path / "stage", meeting, root, "vania", "marwin-inbox")
    assert (staging / "hf_token.txt").read_text().strip() == "hf_secret123"


def test_stage_kernel_substitutes_username(tmp_path):
    root = tmp_path / "proj"
    (root / "kaggle").mkdir(parents=True)
    (root / "kaggle" / "kernel.py").write_text("print('hi')")
    (root / "kaggle" / "kernel-metadata.json").write_text(json.dumps({
        "id": "USERNAME/marwin-processor",
        "dataset_sources": ["USERNAME/marwin-inbox"], "code_file": "kernel.py"}))
    staging = kr.stage_kernel(tmp_path / "kstage", root, "vania",
                              "marwin-inbox", "marwin-processor")
    meta = json.loads((staging / "kernel-metadata.json").read_text())
    assert meta["id"] == "vania/marwin-processor"
    assert meta["dataset_sources"] == ["vania/marwin-inbox"]


def test_push_dataset_creates_when_missing(monkeypatch, tmp_path):
    calls = []
    def fake_kaggle(args):
        calls.append(args)
        if args[:2] == ["datasets", "version"]:
            raise kr.KaggleError("404 - Not Found")
        return "ok"
    monkeypatch.setattr(kr, "_kaggle", fake_kaggle)
    kr.push_dataset(tmp_path)
    assert calls[0][:2] == ["datasets", "version"]
    assert calls[1][:2] == ["datasets", "create"]


def test_push_dataset_creates_on_403(monkeypatch, tmp_path):
    # Live Kaggle (observed 2026-07-10) returns 403 Forbidden, not 404,
    # when versioning a dataset that does not exist yet.
    calls = []
    def fake_kaggle(args):
        calls.append(args)
        if args[:2] == ["datasets", "version"]:
            raise kr.KaggleError(
                "403 Client Error: Forbidden for url: "
                "https://api.kaggle.com/v1/datasets.DatasetApiService/CreateDatasetVersion")
        return "ok"
    monkeypatch.setattr(kr, "_kaggle", fake_kaggle)
    kr.push_dataset(tmp_path)
    assert calls[1][:2] == ["datasets", "create"]


def test_retry_network_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise kr.KaggleError("getaddrinfo failed")
        return "ok"
    assert kr._retry_network(flaky) == "ok"
    assert calls["n"] == 2


def test_retry_network_raises_non_network_immediately(monkeypatch):
    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    calls = {"n": 0}
    def bad():
        calls["n"] += 1
        raise kr.KaggleError("403 Forbidden")
    with pytest.raises(kr.KaggleError, match="403"):
        kr._retry_network(bad)
    assert calls["n"] == 1


def test_wait_for_dataset_polls_until_ready(monkeypatch):
    # A kernel started before the dataset version finishes processing sees
    # an empty mount (observed live 2026-07-10: ModuleNotFoundError inside
    # the kernel). process_meeting must wait for "ready" before kernel push.
    outputs = iter(["processing", "ready"])
    monkeypatch.setattr(kr, "_kaggle", lambda args: next(outputs))
    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    kr.wait_for_dataset("vania/marwin-inbox", timeout_s=300, poll_s=1)


def test_wait_for_dataset_timeout_raises(monkeypatch):
    monkeypatch.setattr(kr, "_kaggle", lambda args: "processing")
    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    with pytest.raises(kr.KaggleError, match="not become ready"):
        kr.wait_for_dataset("vania/marwin-inbox", timeout_s=1, poll_s=1)


def test_wait_for_kernel_tolerates_transient_poll_failures(monkeypatch):
    # A local DNS/network blip mid-poll must not abort a run whose kernel
    # is still executing on Kaggle (observed live 2026-07-10).
    outputs = iter([kr.KaggleError("getaddrinfo failed"),
                    kr.KaggleError("getaddrinfo failed"),
                    'has status "KernelWorkerStatus.COMPLETE"'])
    def fake(args):
        item = next(outputs)
        if isinstance(item, Exception):
            raise item
        return item
    monkeypatch.setattr(kr, "_kaggle", fake)
    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    kr.wait_for_kernel("vania/marwin-processor", timeout_s=300, poll_s=1)


def test_wait_for_kernel_gives_up_after_consecutive_failures(monkeypatch):
    def fake(args):
        raise kr.KaggleError("getaddrinfo failed")
    monkeypatch.setattr(kr, "_kaggle", fake)
    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    with pytest.raises(kr.KaggleError, match="getaddrinfo"):
        kr.wait_for_kernel("vania/marwin-processor", timeout_s=300, poll_s=1)


def test_wait_for_kernel_new_cli_enum_format(monkeypatch):
    # kaggle CLI 2.x prints e.g. 'has status "KernelWorkerStatus.COMPLETE"'
    # (observed live 2026-07-10); the old format had bare '"complete"'.
    outputs = iter(['has status "KernelWorkerStatus.RUNNING"',
                    'has status "KernelWorkerStatus.COMPLETE"'])
    monkeypatch.setattr(kr, "_kaggle", lambda args: next(outputs))
    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    kr.wait_for_kernel("vania/marwin-processor", timeout_s=300, poll_s=1)


def test_wait_for_kernel_new_cli_error_raises(monkeypatch):
    monkeypatch.setattr(
        kr, "_kaggle",
        lambda args: 'has status "KernelWorkerStatus.ERROR"')
    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    with pytest.raises(kr.KaggleError, match="failed"):
        kr.wait_for_kernel("vania/marwin-processor", timeout_s=1, poll_s=1)


def test_wait_for_kernel_completes(monkeypatch):
    outputs = iter(['has status "running"', 'has status "complete"'])
    monkeypatch.setattr(kr, "_kaggle", lambda args: next(outputs))
    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    kr.wait_for_kernel("vania/marwin-processor", timeout_s=300, poll_s=1)


def test_wait_for_kernel_error_raises(monkeypatch):
    monkeypatch.setattr(kr, "_kaggle", lambda args: 'has status "error"')
    with pytest.raises(kr.KaggleError, match="failed"):
        kr.wait_for_kernel("vania/marwin-processor", timeout_s=300, poll_s=1)


def test_kaggle_cli_missing_raises_friendly_error(monkeypatch):
    def raise_not_found(*args, **kwargs):
        raise FileNotFoundError("kaggle")
    monkeypatch.setattr(kr.subprocess, "run", raise_not_found)
    with pytest.raises(kr.KaggleError, match="PREREQS"):
        kr._kaggle(["datasets", "list"])


def test_stage_dataset_ships_mic_label_when_present(tmp_path):
    # The owner's name lives in a git-ignored mic_label.txt, not in code.
    meeting = tmp_path / "m"; meeting.mkdir()
    (meeting / "audio.opus").write_bytes(b"opus")
    root = tmp_path / "proj"
    (root / "marwin").mkdir(parents=True)
    (root / "marwin" / "merge.py").write_text("# merge")
    (root / "marwin" / "transcript.py").write_text("# transcript")
    (root / "mic_label.txt").write_text("Alex", encoding="utf-8")
    staging = kr.stage_dataset(tmp_path / "stage", meeting, root, "u", "marwin-inbox")
    assert (staging / "mic_label.txt").read_text(encoding="utf-8") == "Alex"
