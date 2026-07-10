# Marwin one-time setup (~10 minutes, all free)

## 1. ffmpeg
    winget install ffmpeg
Verify: `ffmpeg -version` prints a version line.

## 2. Python dependencies
    python3 -m pip install -e .
    python3 -m pip install -r requirements.txt

## 3. Kaggle account (free GPU)
1. Sign up at https://www.kaggle.com (use any email)
2. Settings → verify with a phone number (this unlocks GPU access)
3. Settings → API → "Create New Token" — downloads kaggle.json
4. Move it to: C:\Users\Admin\.kaggle\kaggle.json
5. Verify: `kaggle datasets list -m` prints a table (may be empty)

## 4. Hugging Face token (for the diarization model)
1. Sign up at https://huggingface.co
2. Accept the model terms at:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
   - https://huggingface.co/pyannote/embedding
3. Create a read token: Settings → Access Tokens → New token
4. Add it as a Kaggle secret: kaggle.com → your kernel workspace →
   Add-ons → Secrets → name it exactly `HF_TOKEN`
   (First run: `marwin process` creates the kernel; if the secret is
   missing the kernel fails fast — add the secret to the kernel at
   kaggle.com/code/<username>/marwin-processor → Add-ons → Secrets,
   then re-run `marwin process`.)

Privacy note: processing uploads each meeting's audio to your PRIVATE Kaggle dataset; the most recent upload remains there until the next one replaces it.

## 5. Config
    copy config.example.yaml config.yaml
Edit `config.yaml`: set `kaggle.username` to your Kaggle username.
