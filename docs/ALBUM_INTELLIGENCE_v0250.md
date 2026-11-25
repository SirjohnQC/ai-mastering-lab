# AI Mastering Lab v0.25.0 — Album Intelligence (phase 1)

## What works

Album Studio already imports stereo WAVs and stem folders, batches stems through three mix proposals, and runs independently verified 24-bit mastering. This release adds a **read-only reference-based album consistency audit** rather than rewriting that working pipeline.

1. Add album tracks to the existing Album Studio.
2. Run `AUTO PRODUCE ALBUM` and confirm per-track technical QC; imported tracks that already have a validated, local mastered WAV may also be eligible.
3. Under **Chanson de référence**, choose one track that has a completed `qc_pass` master. Unready/error tracks cannot be the reference.
4. Click **✦ Analyser la cohérence**. An independent QThread reads local approved masters, calculates level-independent spectrum profiles, and compares tracks to the chosen reference.
5. A concise per-song report appears in Album Studio, with Δ integrated LUFS (from stored mastering QC), maximum broad-band spectral energy difference in dB, and review warnings. The detailed structured report is saved locally in `sound/output/album_studio/album_consistency.json`.

The reference selection is saved to the user's existing ignored `settings/album_project.json` as a **source path**, so moving tracks up/down doesn't change the reference choice. Selecting another reference invalidates the displayed previous comparison; an explicit Analyze recalculates results.

## Technical scope

- Streaming/seek-sampled stereo WAV analysis with up to 72 FFT slices of 8192 frames, across bands 40–160, 160–600, 600–2400, 2400–8000, 8000–18000 Hz. Relative normalized energy is compared between tracks; this is NOT professional perceptual tonal matching or a correction EQ curve.
- Proper **integrated LUFS and true peak** are read from previously verified per-song QC results, never deduced from sample RMS.
- A `loudness_review` flag is raised when a track differs from the reference by more than 1.5 LUFS. A `spectrum_review` flag appears for a relative-band difference over 4 dB. A true-peak review flag records an unexpected result above -1.0 dBTP despite the recorded QC pass.
- Silence windows are ignored in sampling; spectra are approximate and may reflect deliberate arrangement differences.
- Only QC-pass WAVs actually found on disk can be analyzed. Missing, not-ready and invalid files receive explicit status.
- Source audio, mastered WAVs, plugin settings, caches and personal album entries **never leave the local PC**. This PR contains Python, tests and documentation only.
- The analytical report is read-only: **no automated gain adjustments, EQ, regeneration or re-export**. A spectrally different track may be artistically intended; all warnings are listening prompts, not hard errors.
- An optional step after this phase could compare the three rendered variants for consistency and *suggest* safer album-level choices, always subject to human audition.

## Windows test checklist

1. Switch to `feature/v0.25.0-album-intelligence`; start `python scripts/desktop.py`.
2. Open **Album Mode**. Import 2+ songs with local QC-pass masters (or produce them with the existing album pipeline).
3. In the reference selector choose the track that best represents the desired overall album sound.
4. Click **Analyser la cohérence**, wait for the local comparison. Verify the summary and each track's Δ LUFS / max relative spectral difference.
5. Change the reference and re-run. The results should update, without modifying any master WAV.
6. Reorder tracks; confirm the reference stays attached to the same original source track.
7. Include an unmastered/error track: it should not be selectable as a QC-passed reference.
8. Run `python -m unittest discover -s tests -p "test_album_intelligence_v0250.py"`. Then run earlier tests for mastering and guided UI.
9. Check `git status` before pushing: no `settings/`, `sound/`, `audio/`, stems, masters or personal reports should be published.

## Acceptance caveats

The tests are included but have **not been executed on the user's Windows/PySide6 machine**. The existing Album Mode still contains a number of French legacy labels regardless of English; this is a separate localization pass. UI/Qt performance and existing background album mastering should be tested before merging.

This PR is stacked on v0.24.4 (#13); preserve earlier PR dependency order until validated.
