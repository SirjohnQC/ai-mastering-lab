# v0.23.9 — Smart Gentle Calibration

## What changes
For each of the three Auto Studio premixes, Compare now auditions **two Gentle threshold candidates** on *local, immutable preview copies*. Each candidate is limited to one of the **already calibrated normalized Pro-C 3 threshold points**, `0.85` or `0.70`. Ratio stays at the validated `0.30`, and attack/release at `0.30`. Auto Gain is Off.

Each candidate gets the existing strict **JUCE parameter readback**, WAV integrity and peak checks. A **read-only PCM comparison** then evaluates global/short-window changes, clipping risk, remaining crest factor and disproportionate reduction of loud passages.

Only a candidate with a measurable but modest effect is selected. The ranking targets about **−0.75 dB** average difference in source-defined loud 100-ms windows (a PCM proxy, **NOT** plugin gain reduction). If neither candidate meets conservative conditions, Gentle is an **explicit Original fallback**; the Gentle mastering ♥ is disabled and the persistence API refuses saving it as an approved compressed choice.

The six/now-nine render operations are performed in the existing background worker. Original premix WAVs are never overwritten. There remain **nine player combinations**: 3 premixes × Original/Gentle/Firm; no extra UI tabs or extra manual buttons. All candidate WAVs and their local JSON reports stay inside ignored `settings/pro_c3_song_previews/` sessions.

### Important cache note
`CACHE_RENDER_VERSION = 3` invalidates old preview files intentionally. **First entry into Compare will re-render** two Gentle candidates plus Firm for each premix (9 JUCE renders in total), and perform WAV analysis. Further entries for unchanged source mixes reuse the cache. Diagnostic caching continues separately.

### Known limitations and guardrails
- Only two calibrated threshold settings are tried; the software does not sweep arbitrary threshold dB values.
- This **does not implement Hermes AI reasoning**. That is planned for v0.24.0 after the calibrated rule-based pipeline is validated.
- Candidate scores do not guarantee musical improvement; audible comparison and explicit ♥ remain necessary.
- A fallback cannot be heart-approved as Gentle. Select ♥ Original if no candidate was retained.
- Source PCM window-level change does **not** measure FabFilter gain reduction.
- No uploads, stems, masters or private plugin configuration files committed.

## Acceptance on Windows
1. `git fetch origin`, then switch to `feature/v0.23.9-smart-gentle-calibration`; launch `python scripts/desktop.py`.
2. Open Compare. Expect longer **first** preparation: two Gentle candidate renders + one Firm per mix.
3. Choose Gentle on a song that previously showed `Diff. RMS = −0.003 dB`. Look for **Smart Gentle** status, the chosen *physical threshold text* and measured strong-window RMS change.
4. Compare against Original, check waveform/markers and playback position continuity.
5. If no candidate passed, the UI must explicitly show **Original fallback** and refuse ♥ Gentle; ♥ Original remains available.
6. Reload the same song and enter Compare: confirm cache reuse and no additional JUCE renders.
7. Run `python -m unittest discover -s tests -p "test_smart_gentle_v0239.py"`. Run previous test suites if possible. Real Pro-C 3/JUCE acceptance remains required before merging.

This draft PR builds on v0.23.8; earlier stacked PRs must be merged in dependency order if/when verified.
