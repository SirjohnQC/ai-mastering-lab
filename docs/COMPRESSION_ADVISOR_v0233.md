# v0.23.3 — Measured Compression Advisor

**Status: candidate for Windows audio validation.** This branch builds on the earlier draft PR #1 (v0.23.2). It does NOT merge or modify `main`.

## Behavior

- Compare now offers **Naturel / Équilibré / Énergique** within the same panel.
- After the cached nine-way WAV comparison finishes, an explainable heuristic recommends Original, Gentle or Firm *for the currently selected mix*.
- The recommendation uses observed PCM crest factor (peak vs RMS), RMS change, and peak/clipping safeguards.
- If the Gentle and Original WAVs have identical samples, Gentle is **ineligible** to be recommended.
- The **Écouter la suggestion** control switches the existing audio player selection only. It does not alter a JUCE effect, does not change the cached previews and **never approves a mastering source**.
- The existing **♥** action remains mandatory to master any processed variant.
- Audio, stems, plugin parameters and private configurations are never committed or uploaded.

## Important limitation

This is **not Hermes inference** and does **not** estimate plugin gain reduction in decibels. The thresholds are cautious heuristics, not objective audio-quality assessments. It ranks the already-rendered calibrated Original/Gentle/Firm **rather than changing Pro-C 3 parameters per song**. Next step after validation: experiment with discrete calibrated parameter grids for song-specific gentle/firm renders; Hermes could use validated measurements and explicit human approval.

## Windows acceptance

1. Check out feature branch `feature/v0.23.3-compression-advisor`, start `python scripts/desktop.py`.
2. In Compare, wait for all nine WAVs to be ready with v0.23.2 measurements.
3. For the same Balanced mix toggle Naturel / Équilibré / Énergique. The label should update without rerendering or resetting playback.
4. Click **Écouter la suggestion**; it selects the indicated compression but does not click ♥.
5. Try Vocal Focus and Punchy; advisor follows the selected mix.
6. Confirm very low-crest or clipping-prone processed WAVs are not recommended.
7. Verify the heart gate still sends Original to mastering until explicitly approved.

Tests added: `python -m unittest discover -s tests -p "test_compression_advisor_v0233.py"` (run on Windows with project dependencies installed). Verify the real JUCE/Qt behavior before merging.
