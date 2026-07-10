# Marwin 🎙️

Personal meeting-intelligence copilot — free, local-first, bilingual.

Marwin sits in your meetings as a silent attendee: it records locally
(your mic + system audio on separate channels), transcribes
English/Urdu code-switched speech on a **free Kaggle GPU**
(Whisper large-v3 + pyannote speaker diarization), then uses headless
**Claude Code** calls to extract action items, decisions, deadlines,
risks, and open questions — and renders formatted Minutes of Meeting
in a local dashboard.

Built because Teams transcripts are hopeless at English/Urdu
code-switching. Total running cost: **$0** (free GPU quota + an
existing Claude plan).

## What you get per meeting

- `transcript.json` — speaker-labeled, your own voice tagged by name
  (mic channel), Urdu in proper Urdu script — never Devanagari
- `intelligence.json` — tasks, decisions, questions, risks, deadlines,
  topics, summary; every item QA-scored 0–100 against the transcript
- `minutes.md` — clean Minutes of Meeting (agenda, discussion summary,
  action-items table, key decisions), rendered in the dashboard
- A Streamlit dashboard with intelligence cards, low-confidence ⚠️
  flags, and an Original⇄English transcript toggle

## Privacy by design

- Audio, transcripts, and minutes **never leave your machine**, except:
  transient processing in **your own private** Kaggle workspace, and
  transcript text sent to Anthropic through your own Claude plan.
- No third-party services, no telemetry, no accounts other than your
  own Kaggle / Hugging Face / Claude.
- `meetings/`, tokens, and real config are git-ignored — a clone of
  this repo contains code only.
- Record only meetings you are allowed to record. Check your
  workplace's policy first.

## Quick start

0. Open a terminal in this folder (all marwin commands run from here)
1. Complete PREREQS.md (one-time, ~10 min, all free)
2. `marwin record --title "team sync"`  (Enter stops recording)
3. `marwin run`                          (transcribe ~10 min + analyze ~3 min)
4. `marwin dashboard`                    (transcript, tasks, decisions, minutes)

Outputs per meeting: transcript.json · intelligence.json · minutes.md (rendered in the dashboard)

## Personalize

- Copy `config.example.yaml` to `config.yaml` and set your Kaggle
  username.
- Create a `mic_label.txt` file in this folder containing your name —
  your own voice (the mic channel) gets labeled with it in transcripts.
  Without the file, it's labeled "Me". The file is git-ignored, so your
  name stays out of the repository.

## How it works

```
laptop mic ─┐                         ┌─ Whisper large-v3 (transcribe)
            ├─ 2-channel recording ──►│  pyannote (who spoke when)      free Kaggle GPU
system audio┘        (WASAPI)         └─ back to your laptop
                                             │
                              headless Claude Code calls (your plan)
                                             │
                    normalize script (English/Urdu only) → 7 extraction
                    agents + QA scorer → intelligence.json → minutes.md
                                             │
                                   Streamlit dashboard (local)
```

Everything is cached and resumable: re-running a stage only does the
missing work.

## License

MIT — see [LICENSE](LICENSE).
