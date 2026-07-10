"""Orchestrates the free Kaggle GPU run: push audio+code as a private
dataset, push the kernel, poll, download transcript.json."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import transcript as transcript_mod


class KaggleError(RuntimeError):
    pass


def _kaggle(args: list[str]) -> str:
    # PYTHONUTF8: the kaggle CLI crashes writing Unicode kernel logs on
    # Windows (cp1252 'charmap' error, observed live 2026-07-10).
    env = {**os.environ, "PYTHONUTF8": "1"}
    try:
        result = subprocess.run(["kaggle", *args], capture_output=True,
                                text=True, encoding="utf-8",
                                errors="replace", env=env)
    except (FileNotFoundError, OSError):
        raise KaggleError(
            "kaggle CLI not found — install it with: python3 -m pip install "
            "kaggle, then set up kaggle.json (see PREREQS.md)")
    if result.returncode != 0:
        raise KaggleError(
            f"kaggle {' '.join(args[:2])} failed: "
            f"{(result.stderr or result.stdout).strip()[-400:]}")
    return result.stdout


_NETWORK_MARKERS = ("getaddrinfo", "max retries", "connection", "resolve",
                    "timed out")


def _retry_network(fn, attempts: int = 3, wait_s: int = 10):
    """Retry fn on transient network failures (flaky Wi-Fi dropped two live
    runs on 2026-07-10). Non-network KaggleErrors raise immediately."""
    for attempt in range(attempts):
        try:
            return fn()
        except KaggleError as e:
            msg = str(e).lower()
            if attempt + 1 < attempts and any(m in msg for m in _NETWORK_MARKERS):
                print(f"network hiccup — retrying in {wait_s}s "
                      f"({attempt + 1}/{attempts - 1})...")
                time.sleep(wait_s)
                continue
            raise


def stage_dataset(staging: Path, meeting_dir: Path, project_root: Path,
                  username: str, slug: str) -> Path:
    staging = Path(staging)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copy2(meeting_dir / "audio.opus", staging / "audio.opus")
    for mod in ("merge.py", "transcript.py"):
        shutil.copy2(project_root / "marwin" / mod, staging / mod)
    # Kaggle user secrets don't reach API-pushed kernels (observed live
    # 2026-07-10): ship the HF token inside the private dataset instead.
    token_file = project_root / "hf_token.txt"
    if token_file.exists():
        shutil.copy2(token_file, staging / "hf_token.txt")
    # Personal mic label (git-ignored): keeps the owner's name out of the
    # public code while their own transcripts still use it.
    label_file = project_root / "mic_label.txt"
    if label_file.exists():
        shutil.copy2(label_file, staging / "mic_label.txt")
    (staging / "dataset-metadata.json").write_text(json.dumps({
        "title": slug, "id": f"{username}/{slug}",
        "licenses": [{"name": "unknown"}]}, indent=2))
    return staging


def push_dataset(staging: Path) -> None:
    try:
        _kaggle(["datasets", "version", "-p", str(staging), "-m", "marwin upload"])
    except KaggleError as e:
        # Live Kaggle returns 403 Forbidden (not 404) when versioning a
        # dataset that does not exist yet — observed 2026-07-10.
        msg = str(e).lower()
        if any(s in msg for s in ("404", "not found", "403", "forbidden")):
            _kaggle(["datasets", "create", "-p", str(staging)])
        else:
            raise


def wait_for_dataset(ref: str, timeout_s: int = 300, poll_s: int = 10) -> None:
    """Block until the dataset version finishes processing. A kernel started
    against a still-processing dataset sees an empty mount (observed live
    2026-07-10)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if "ready" in _kaggle(["datasets", "status", ref]).lower():
            return
        time.sleep(poll_s)
    raise KaggleError(
        f"Dataset {ref} did not become ready within {timeout_s}s — "
        f"check https://www.kaggle.com/datasets/{ref}")


def stage_kernel(staging: Path, project_root: Path, username: str,
                 dataset_slug: str, kernel_slug: str) -> Path:
    staging = Path(staging)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copy2(project_root / "kaggle" / "kernel.py", staging / "kernel.py")
    meta = json.loads((project_root / "kaggle" / "kernel-metadata.json")
                      .read_text(encoding="utf-8"))
    meta_text = json.dumps(meta).replace("USERNAME/marwin-processor",
                                         f"{username}/{kernel_slug}")
    meta_text = meta_text.replace("USERNAME/marwin-inbox",
                                  f"{username}/{dataset_slug}")
    (staging / "kernel-metadata.json").write_text(meta_text, encoding="utf-8")
    return staging


def push_kernel(staging: Path) -> None:
    _kaggle(["kernels", "push", "-p", str(staging)])


def wait_for_kernel(ref: str, timeout_s: int = 3600, poll_s: int = 30) -> None:
    deadline = time.monotonic() + timeout_s
    failures = 0
    while time.monotonic() < deadline:
        # Old CLI: 'has status "complete"'; kaggle CLI 2.x (observed live
        # 2026-07-10): 'has status "KernelWorkerStatus.COMPLETE"'. Match on
        # the bare words so both formats work; check error before complete.
        try:
            status = _kaggle(["kernels", "status", ref]).lower()
        except KaggleError:
            # Transient local network blip must not abort a kernel that is
            # still running on Kaggle (observed live 2026-07-10).
            failures += 1
            if failures >= 3:
                raise
            time.sleep(poll_s)
            continue
        failures = 0
        if "error" in status or "cancel" in status:
            raise KaggleError(
                f"Kernel {ref} failed on Kaggle — check the kernel log at "
                f"https://www.kaggle.com/code/{ref}")
        if "complete" in status:
            return
        time.sleep(poll_s)
    raise KaggleError(f"Kernel {ref} did not finish within {timeout_s}s")


def download_output(ref: str, dest_dir: Path) -> Path:
    _kaggle(["kernels", "output", ref, "-p", str(dest_dir)])
    out = Path(dest_dir) / "transcript.json"
    if not out.exists():
        raise KaggleError("Kernel finished but produced no transcript.json — "
                          f"check the log at https://www.kaggle.com/code/{ref}")
    return out


def process_meeting(meeting_dir: Path, cfg: dict, project_root: Path) -> Path:
    username = cfg["kaggle"]["username"]
    if not username:
        raise KaggleError("kaggle.username is empty — copy config.example.yaml "
                          "to config.yaml and fill it in (see PREREQS.md)")
    dataset_slug = cfg["kaggle"]["dataset_slug"]
    kernel_slug = cfg["kaggle"]["kernel_slug"]
    scratch = project_root / ".kaggle-staging"

    print("1/4 Uploading audio to your private Kaggle dataset...")
    ds = stage_dataset(scratch / "dataset", meeting_dir, project_root,
                       username, dataset_slug)
    _retry_network(lambda: push_dataset(ds))
    wait_for_dataset(f"{username}/{dataset_slug}")

    print("2/4 Starting the GPU kernel...")
    kn = stage_kernel(scratch / "kernel", project_root, username,
                      dataset_slug, kernel_slug)
    _retry_network(lambda: push_kernel(kn))

    ref = f"{username}/{kernel_slug}"
    print("3/4 Waiting for Kaggle (typically ~10 min for a 1-hour meeting)...")
    wait_for_kernel(ref)

    print("4/4 Downloading transcript...")
    out = _retry_network(lambda: download_output(ref, meeting_dir))
    transcript_mod.load(out)  # validates schema
    return out
