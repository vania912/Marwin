import argparse
import shutil
import sys
import threading
from pathlib import Path

from .config import load_config
from .meetings import create_meeting_dir, latest_unprocessed, latest_unanalyzed, list_meetings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marwin",
                                     description="Personal meeting intelligence")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="record a meeting (Enter stops)")
    rec.add_argument("--title", default=None, help="meeting title")
    rec.add_argument("--recover", action="store_true",
                     help="finish a recording interrupted by a crash")

    proc = sub.add_parser("process", help="transcribe on Kaggle")
    proc.add_argument("meeting", nargs="?", default=None,
                      help="meeting folder name (default: latest unprocessed)")

    an = sub.add_parser("analyze", help="extract intelligence + minutes")
    an.add_argument("meeting", nargs="?", default=None,
                    help="meeting folder name (default: latest unanalyzed)")
    an.add_argument("--force", action="store_true",
                    help="redo all Claude calls even if cached")

    runp = sub.add_parser("run", help="process then analyze")
    runp.add_argument("meeting", nargs="?", default=None)

    sub.add_parser("dashboard", help="open the local dashboard")
    return parser


def check_disk_space(path: Path, min_gb: float) -> None:
    free_gb = shutil.disk_usage(path).free / 2**30
    if free_gb < min_gb:
        raise RuntimeError(
            f"Only {free_gb:.1f} GB free — Marwin needs at least {min_gb} GB "
            f"to record safely. Free up space and retry.")


def _cmd_record(args, root: Path, cfg: dict) -> int:
    from .ffmpegw import require_ffmpeg
    from .recorder import record_meeting, finalize_recording
    from .chunks import has_chunks
    require_ffmpeg()
    meetings_root = root / cfg["meetings_dir"]

    if args.recover:
        for m in list_meetings(meetings_root):
            if has_chunks(m["dir"]) and not (m["dir"] / "audio.opus").exists():
                print(f"Recovering {m['dir'].name} ...")
                opus = finalize_recording(m["dir"])
                print(f"Recovered -> {opus}")
                return 0
        print("Nothing to recover.")
        return 0

    if not args.title:
        print("error: --title is required (or use --recover)", file=sys.stderr)
        return 2
    check_disk_space(root, cfg["recording"]["min_free_gb"])

    from .recorder import mic_peak, mic_looks_muted
    print("Pre-flight: checking your microphone (2s)...")
    try:
        peak = mic_peak()
    except Exception as e:  # pre-flight must never block a recording outright
        print(f"warning: mic pre-flight failed ({e}) — continuing")
        peak = None
    if peak is not None and mic_looks_muted(peak):
        print("!! MIC LOOKS MUTED — check the mic-mute key (F4, LED must be")
        print("   OFF) and Windows Settings > Sound > Input level.")
        if input("Record anyway? [y/N] ").strip().lower() != "y":
            print("Aborted — unmute the mic and rerun.")
            return 1
    print("Reminder: meeting audio must be audible on THIS laptop "
          "(speakers or wired headset).")

    meeting_dir = create_meeting_dir(meetings_root, args.title)
    stop = threading.Event()
    print(f"Recording '{args.title}' -> {meeting_dir.name}")
    print("Press Enter to stop recording...")
    waiter = threading.Thread(target=lambda: (input(), stop.set()), daemon=True)
    waiter.start()
    opus = record_meeting(meeting_dir, cfg, stop)
    print(f"Saved {opus} — next: marwin process")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = Path.cwd()
    cfg = load_config(root)
    try:
        if args.command == "record":
            return _cmd_record(args, root, cfg)
        if args.command == "process":
            from .kaggle_runner import process_meeting  # Task 11
            meetings_root = root / cfg["meetings_dir"]
            meeting = (meetings_root / args.meeting if args.meeting
                       else latest_unprocessed(meetings_root))
            if meeting is None:
                print("No unprocessed meetings found.", file=sys.stderr)
                return 1
            transcript = process_meeting(meeting, cfg, root)
            print(f"Transcript ready -> {transcript}")
            return 0
        if args.command == "analyze":
            from .analyze import analyze_meeting
            meetings_root = root / cfg["meetings_dir"]
            meeting = (meetings_root / args.meeting if args.meeting
                       else latest_unanalyzed(meetings_root))
            if meeting is None:
                print("No analyzed-pending meetings found.", file=sys.stderr)
                return 1
            out = analyze_meeting(meeting, force=args.force)
            print(f"Intelligence ready -> {out}")
            print(f"Minutes -> {meeting / 'minutes.md'} (view in: marwin dashboard)")
            return 0
        if args.command == "run":
            from .kaggle_runner import process_meeting
            from .analyze import analyze_meeting
            meetings_root = root / cfg["meetings_dir"]
            meeting = (meetings_root / args.meeting if args.meeting
                       else latest_unprocessed(meetings_root) or latest_unanalyzed(meetings_root))
            if meeting is None:
                print("No meetings to run.", file=sys.stderr)
                return 1
            if not (meeting / "transcript.json").exists():
                process_meeting(meeting, cfg, root)
            out = analyze_meeting(meeting)
            print(f"Done -> {out}")
            return 0
        if args.command == "dashboard":
            import subprocess
            app = Path(__file__).parent / "dashboard" / "app.py"
            return subprocess.call([sys.executable, "-m", "streamlit",
                                    "run", str(app)])
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
