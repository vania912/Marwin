from marwin.merge import detect_lang, channel_energy, dominant_turn, assign_speakers


def test_detect_lang():
    assert detect_lang("We'll finish the blueprint by Friday") == "en"
    assert detect_lang("یہ کام جمعہ تک ہو جائے گا") == "ur"
    assert detect_lang("ok جی بالکل، deadline جمعہ ہے") == "ur"  # mostly Urdu


def test_channel_energy_windows():
    rms = [0.0, 0.1, 0.9, 0.9]  # hop = 0.5s -> covers 0..2.0s
    assert channel_energy(rms, 0.5, 1.0, 2.0) == 0.9
    assert channel_energy(rms, 0.5, 5.0, 6.0) == 0.0  # out of range


def test_dominant_turn_picks_max_overlap():
    turns = [
        {"start": 0.0, "end": 4.0, "speaker": "S1"},
        {"start": 3.0, "end": 10.0, "speaker": "S2"},
    ]
    assert dominant_turn(turns, 0.0, 3.5) == "S1"
    assert dominant_turn(turns, 3.5, 8.0) == "S2"
    assert dominant_turn(turns, 20.0, 21.0) is None


def test_assign_speakers_mic_vs_loopback():
    wsegs = [
        {"start": 0.0, "end": 1.0, "text": "hello from mic", "confidence": 0.9},
        {"start": 1.0, "end": 2.0, "text": "reply from the host", "confidence": 0.8},
        {"start": 2.0, "end": 3.0, "text": "silence mystery", "confidence": 0.5},
    ]
    turns = [{"start": 1.0, "end": 2.0, "speaker": "S1"}]
    mic_rms = [0.9, 0.9, 0.1, 0.1, 0.0, 0.0]   # loud 0-1s
    loop_rms = [0.1, 0.1, 0.9, 0.9, 0.0, 0.0]  # loud 1-2s
    out = assign_speakers(wsegs, turns, mic_rms, loop_rms, hop=0.5)
    assert out[0]["speaker"] == "Me"
    assert out[1]["speaker"] == "S1"
    assert out[2]["speaker"] == "Unknown"
    assert all("lang" in seg for seg in out)
