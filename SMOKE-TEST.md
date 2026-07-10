# Marwin Phase 1 end-to-end smoke test

Prereqs: PREREQS.md completed. Takes ~20 minutes. Open a terminal in this folder (all marwin commands run from here).

1. Play a YouTube video with at least two people speaking (an
   interview or panel works well) (this simulates "other
   participants" on the loopback channel).
2. Run: `marwin record --title "smoke"`
3. Speak 3-4 sentences into your mic — mix English and Urdu.
   Let the video talk in between. After ~2 minutes, press Enter.
   PASS: `meetings/<date>-smoke/audio.opus` exists (~0.5-1.2 MB).
4. Run: `marwin process`
   PASS: four progress lines print; after ~5-10 min:
   "Transcript ready -> ...transcript.json"
5. Run: `marwin dashboard`
   PASS: your sentences are attributed to your configured name (left channel);
   the video's speech is labeled with distinct speaker IDs (e.g.,
   SPEAKER_00/SPEAKER_01); Urdu text renders in Urdu script
   with a 🇵🇰 badge; timestamps are plausible.
6. Crash recovery: start `marwin record --title "crash"`, kill the
   terminal after ~90 seconds, then run `marwin record --recover`.
   PASS: "Recovered -> ...audio.opus" and the file plays
   (use VLC or `ffplay`).

Record what failed (if anything) in this file under "## Results".
