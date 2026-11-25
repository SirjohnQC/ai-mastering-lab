# Auto Studio v0.23.2 — Compression Audition Diagnostics

This update addresses why Original/Gentle/Firm appeared to have the same waveform and sound.

## Actual behavior

- The **selected mix + compression** now determines the waveform displayed in the unified Compare panel.
- All nine stereo WAVs are measured after render or valid cache reuse by a worker thread.
- The same active path is shown in the UI and used by its corresponding Qt audio player.
- RMS dBFS, sample peak dBFS, crest factor, and (for Gentle/Firm) the measured RMS difference and null-test residual relative to Original are shown.
- If two WAVs have **exactly identical PCM samples**, the UI warns that Pro-C 3 routing/bypass must be investigated.
- These metrics do **not** claim to measure FabFilter's internal gain reduction, and a subtle audible difference may still be legitimate.
- The nine waveform data sets are stored locally under `settings/pro_c3_unified_diagnostics.json` keyed by input premix fingerprints. Neither source songs nor generated masters are modified.
- The previous JUCE render cache, synchronized nine-player transport and pink-heart explicit mastering approval remain intact.
- There is no new Hermes auto-compression inference.

## Windows acceptance test

1. Pull PR locally into a working branch; do not merge into `main` until validated.
2. Launch `python scripts/desktop.py`; load a stereo 48 kHz song and generate all 3 premixes.
3. Enter **Comparer**. Wait for "9 combinaisons" and the diagnostics indicator.
4. Select **Balanced + Original**, then **Gentle** and **Firm**. Verify `WAV actif` changes, waveform updates, and dBFS metrics appear.
5. Untick RMS listening-level matching, play a loud chorus, then toggle Gentle/Firm. Compare true audible changes.
6. If the warning "WAV STRICTEMENT IDENTIQUE" appears, run the existing `python run_diagnostics.py` and investigate VST rendering/readback before trusting compression.
7. Switch mix while playing: all waveform and metric data must follow the active combination without restarting the song.
8. Re-enter Compare: no JUCE rerender if source premixes unchanged.
9. ♥ a version and verify Mastering selects the exact explicitly approved WAV. Without ♥, original premix must remain the mastering source.
10. Stop, close, and reopen: no audio should continue playing.

## Scope and caveats

The code and synthetic-WAV math were inspected; real FabFilter/JUCE and the Windows Qt multimedia backend are **not** available in the automated testing environment. Verify real playback manually before merging.

Only Python/code files are changed. All `audio/` trees, `settings/` runtime audio and song materials stay LOCAL and should remain ignored in the public repo.

### Implementation

- `src/mastering_lab/compare_visual_diagnostics.py`: streaming, read-only nine-WAV measurement and min/max envelope generation.
- `src/mastering_lab/unified_comparison.py`: diagnostics in PrepareNineWorker, cached local reports, active PCM waveform, route and metrics.
- `tests/test_compare_v0232.py`: synthetic independent audio vs identical-file warning and routing invariants.
- `src/mastering_lab/version.py`: v0.23.2.
