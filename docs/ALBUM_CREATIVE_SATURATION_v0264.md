# AI Mastering Lab v0.26.4 — Creative Saturation A/B

## What this adds

In Album Mode, after a QC-pass master has been analyzed against the external reference, open that song's **♫ A/B** dialog. Alongside Reference Match and Creative EQ, choose:

- **Saturation · Tape**: smooth symmetric digital tanh saturation (not a hardware tape simulation).
- **Saturation · Tube**: softly asymmetric transfer curve, introducing some even-order components (not a physical tube circuit).
- **Saturation · Soft Clip**: smooth cubic saturation curve, not hard digital clipping.

The A/B dialog shows two bounded controls for these three styles:
- **Drive** from **0.2 to 2.5**, default 1.0.
- **Wet Mix** from **5% to 40%**, default 20%.

Changing either control invalidates the old B; click **Préparer B · Saturation ...** to render the new version. A stays the same. The B button and active listening indicator identify the chosen saturation style.

## Audio engine / safety

- Saturation operates on local stereo WAV blocks, with **4× oversampling** using scipy.signal.resample_poly to reduce nonlinear aliasing. Small overlapping blocks help avoid boundaries. Requires already-available numpy, scipy and soundfile from the project analysis dependencies.
- Processing makes a **separate WAV in the ignored local A/B cache**, never overwriting a master, source stems or the standalone reference.
- After processing, FFmpeg measures integrated LUFS; B is compensated to match A within **±0.25 LU**. The complete output undergoes a separate **True Peak ≤−1 dBTP** check.
- If the B preview breaches True Peak, the render automatically retries with effective saturation strength **100%, 75%, 50%, 25%**, reducing both drive and wet mix conservatively. The accepted actual strength, drive and mix are shown in the UI and recorded in a local manifest. There is no hidden limiter or forced master replacement.
- If even the gentlest preview cannot maintain both the peak ceiling and level comparison, **B is refused**, with A left unchanged.
- Input and rendering metadata remain stored only on the local machine, and the cache keys distinguish mode/style/drive/mix so earlier previews cannot be mistaken for new settings.
- The existing **♥ approval** records only the local preview decision for a future final export; it does **not** declare B to be Spotify/distribution ready.

## Important limits

- These are **digital approximations of saturation characters**, not physically accurate tape/tube models or a licensed third-party VST. The results are intended for listening, not automatic defect removal.
- Saturation can emphasize artificial sibilance, metallic highs, ringing or other generative-audio artifacts. More saturation is not always better.
- Saturation here applies **to a completed master WAV only**. Intelligent targeted saturation on individual stems is a later, separate feature, where effect routing and artifact detection can be more selective.
- Sample-accurate switching across two independent Qt Multimedia players is not yet guaranteed. This release retains v0.26.2's safer preloaded A/B transport.

## Windows acceptance

1. Switch to `feature/v0.26.4-creative-saturation-ab`, then `python scripts/desktop.py`.
2. Open Album Mode, select standalone reference WAV, analyze already mastered QC-pass songs.
3. Open **Kids in Love → ♫ A/B**, select **Saturation · Tape**, check Drive 1.0 and Mix 20%, then **Préparer B**.
4. When the B button is enabled, switch A↔B during a verse or chorus and verify the active listening label switches along with the audio.
5. Try Tube and Soft Clip, and adjust Drive/Mix. Each new setting should create or reuse its own local cache; changing controls must not silently reuse the previous B.
6. Inspect B's JSON manifest for `mode:saturation`, `saturation_style`, `drive`, `wet_mix`, `intensity`, actual LUFS and verified True Peak. Ensure A and the original QC report remain unchanged.
7. If the peak ceiling is exceeded, look for an intensity reduction or a safe refusal. Never bypass QC to force B to play.
8. Run `python -m unittest discover -s tests -p "test_album_saturation_v0264.py"` and earlier album tests.

This PR is stacked on v0.26.3 (#26), and is kept **draft** pending actual Windows/PySide6/FFmpeg audio verification. No personal WAVs, stems, references, settings or mastering reports are committed to GitHub.
