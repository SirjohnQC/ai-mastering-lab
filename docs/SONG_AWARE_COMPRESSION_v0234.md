# AI Mastering Lab v0.23.4 — Song-aware Pro-C 3 (preview)

## Goal
Gentle was sometimes too subtle to see or hear. This release selects *a small number of already-probed Pro-C 3 normalized parameter values based on each mix's measured PCM*, then renders real preview copies. It does **not** change the source, bypass JUCE safety, or approve mastering automatically.

## New behavior
- When Compare creates three mixes' Gentle/Firm preview copies, it analyzes each premix's real WAV peak, RMS and crest factor on a worker thread.
- **Gentle** uses threshold normalized `0.70` instead of `0.85` only for a relatively quiet and transient source (`peak <= -8 dBFS`, `crest >= 11 dB`). Ratio remains `0.30`.
- **Firm** backs off threshold from `0.70` to `0.85` for a dense mix (`crest <= 9 dB`); ratio remains `0.70`.
- Attack and release remain at previously probed normalized `0.30` each; Auto Gain stays Off.
- There is **no interpolation**, no guessed plugin parameters, no Hermes decision about compression, and no claim of calibrated gain reduction. Numbers displayed in Compare are *normalized Pro-C 3 grid coordinates*, not threshold dB or ratio units.
- The existing strict `getText` grid lookup and JUCE parameter readback validate the actual applied values. Invalid/missing plugin reports fail the render instead of bypassing.
- New reports include `adaptive_plan` with input PCM measurements and choices. The reports and all rendered user audio are stored locally in `settings/`.
- `CACHE_RENDER_VERSION = 2` intentionally invalidates old Gentle/Firm previews, preventing a v0.23.3 fixed render from appearing to be adaptive. Future launches reuse only the corresponding new session cache.
- Original/Gentle/Firm remain the three options; nine audio clocks remain synchronized and the single shared waveform follows the selected WAV.
- The pink ♥ approval remains required for a processed version to reach Mastering.

## How to test on Windows
1. Switch to `feature/v0.23.4-song-aware-proc3` and launch `python scripts/desktop.py`.
2. Load a 48 kHz stereo mix between 2 seconds and 10 minutes. Go to Compare. The **first load will rerender all six Pro-C 3 copies**; this is expected once after the cache version bump.
3. Check Gentle and Firm on Balanced/Vocal Focus/Punchy. The RMS/crest metrics should follow the correct WAV, while the selected track lists its actual normalized threshold/ratio settings.
4. A quiet, transient-heavy mix should receive Gentle threshold `0.70`; a high-level mix should stay at `0.85`. A dense mix can receive a less aggressive Firm threshold.
5. Press play and switch while listening. It should not restart the song. Compare with RMS listening match on and off, especially loud choruses.
6. Verify no original changed on disk, and ♥ remains the only way to select a compressed mastering source.
7. Exit/re-enter Compare and confirm the cache prevents redundant renders with unchanged inputs.
8. Execute `python -m unittest discover -s tests -p "test_adaptive_pro_c3_v0234.py"` for tests; requires project dependencies.

## Caveats
- This is **a deliberately small, hand-built heuristic** based on peak and crest, not an AI model and not a musical quality guarantee.
- DSP response cannot be inferred from normalized plugin parameters. Continue comparing measured WAVs and auditioning by ear.
- On Windows, real JUCE host and FabFilter Pro-C 3 need manual acceptance testing before merging.
- Commit only code and tests. No `audio/` contents, songs, stems, or local `settings/` runtime data belong in GitHub.
