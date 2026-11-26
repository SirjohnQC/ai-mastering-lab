# AI Mastering Lab v0.26.0 — Reference Tonal Matching (conservative A/B)

## This release

After Album Intelligence compares your **QC-pass album masters** against a chosen **external standalone WAV reference** (or an eligible QC-pass album track), select an album song and open its per-song **♫ A/B** dialog.

- **A** always plays the original completed master WAV, untouched.
- **B** is an optional locally rendered 24-bit PCM WAV with one or two **very gentle EQ filters**, based on the most substantial measured broad-band spectral differences relative to the reference.
- Unlike the former level-only v0.25.6 B, this B is a **tonal** change even when A and the reference already have similar integrated LUFS.
- The processing deliberately **does not reproduce exact reference EQ**, nor automatically add EQ if the bands are already close or appear unreliable. The broad FFT ratios reflect both instrument arrangements and timbre. No band difference is interpreted as a literal gain command.
- FFmpeg's built-in equalizer filter is used for the first prototype (not FabFilter Pro-Q yet). Maximum **two** EQ moves: **±1.25 dB** for low/mid/presence bands and **±0.6 dB** for the highest band. One-octave bandwidth around representative centers.
- A and B are independently measured for integrated LUFS and True Peak. After EQ, B is adjusted to stay within **0.25 LU** of A. That compensation is not used to chase the reference's loudness.
- No B is offered if independent measurement detects **True Peak above −1.0 dBTP**, an impossible safe loudness match, or extreme/invalid spectral differences.
- B is cached in `sound/output/album_studio/ab_previews/` as an audition-only WAV with manifest detailing the filters, loudness and peak; the original WAV, QC status, album sequence, external reference and stems are unchanged.
- Existing A/B player retains its single transport and attempts to restore position while switching; the **♥ approval** only records a decision in local B's manifest for a future final export. **It does not replace A or certify B for distribution.**
- The existing v0.25.6 level-only implementation remains available as a separate backend module, but the dialog's B button now uses the tonal module.

## Safety / exclusions

- A spectrally different acoustic song need not match an aggressive punk song. Review every suggested filter by ear.
- No automatic reference-driven compression, Pro-Q 4 preset, multi-band matching, A/B/C or album re-export yet.
- The algorithm deliberately prevents an **A/B loudness bias**, but cannot guarantee perceptual loudness equivalence at all moments.
- The EQ is not an approved album-mastering chain; B must pass the complete release QC pipeline in a future explicit export workflow, and must be auditioned first.
- Only numeric summaries are used; all audio and manifests remain local. GitHub commits include code, tests and documentation only.

## Windows checklist

1. Fetch branch `feature/v0.26.0-reference-tonal-ab`; run `python scripts/desktop.py`.
2. Album Mode: choose a standalone reference WAV; ensure the album masters are QC-pass, then run **Analyser la cohérence**.
3. Click **♫ A/B** on a specific song card; its dialog should show that song's name.
4. Click **Préparer B · Tonal Match**. For a clear spectral difference, B should be rendered; filter frequencies, ±dB changes, matched LUFS and verified TP should be shown.
5. Switch A↔B mid-refrain and compare. B should not win merely by being louder. If all relevant differences are small, or safe peak/headroom cannot be maintained, no B is produced.
6. Listen to different songs; confirm the cached B and manifest correspond to each source. Changing reference and rerunning Album Intelligence should produce different proposals, not reuse unrelated old previews.
7. Check source masters and original QC reports are unchanged; pressing ♥ only approves the preview for a *future* export.
8. Run `python -m unittest discover -s tests -p "test_reference_tonal_ab_v0260.py"` and prior album tests. The FFmpeg equalizer filter has been smoke-tested on a synthetic 24-bit stereo WAV; actual Windows/PySide6 + end-to-end mastering acceptance remains required.

## Compatibility

This branch is stacked on v0.25.8 (#22) and is intentionally a draft until the user confirms the A/B playback, the original/master separation and QA on their local Windows environment.
