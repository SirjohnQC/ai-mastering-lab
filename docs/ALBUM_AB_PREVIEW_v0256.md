# v0.25.6 — Album A/B Preview (first safe level-only alternative)

## What this update actually does
After Album Intelligence analyzes local QC-passed masters against the selected album WAV reference, choose a song in Album Studio's track list and click **♫ Écouter Original / Ajusté (A/B)**. A dialog presents a **single QMediaPlayer** shared between A (original master) and B (alternate preview). The transport attempts to retain current playback time and play state when switching variants.

Click **Préparer l’aperçu ajusté** to create B in a local cache directory `sound/output/album_studio/ab_previews/`. The output is 24-bit PCM stereo WAV, obtained through FFmpeg's volume filter only. It NEVER overwrites A and is NEVER presented as an independently fully certified distribution master.

The target correction is bounded to **±1.0 dB**, applied only when measured integrated LUFS differs from album reference by over 0.5 LUFS. For positive gain the available true peak headroom is measured and a −1.2 dBTP provisional ceiling is honored. An independent FFmpeg measurement of the rendered B must pass **≤−1.0 dBTP** before audition is offered. If a useful safe adjustment is impossible, the app explains that rather than forcing one. B is cached by master source identity, file size/mtime and bounded gain.

The **♥ approval** stores `approved=true` in B's local manifest for a potential *future* export workflow. It does not replace the original master, modify the QC state or run an exporter. No automatic approval.

## Scope limitations
- This is the first real A/B **level-only** prototype. It does **not** implement reference-guided EQ, multiband compression, spectral matching or live VST processing. Album Match Advisor's sampled FFT band recommendations are not reliable enough to turn directly into Pro-Q EQ parameters.
- Differences in artistic intent, arrangement and perceived loudness must be judged by ear. Matching integrated LUFS alone does not certify album cohesion.
- A/B player switches source while restoring media position; any actual playback transition jitter under Qt Multimedia must be tested locally on Windows.
- No source audio or personal JSON is added to GitHub; preview WAV and approval manifest stay local.

## Windows verification
1. Checkout `feature/v0.25.6-album-ab-preview` and run `python scripts/desktop.py`.
2. In Album Studio choose standalone reference WAV and analyze at least one QC-passed album track. Select a measured song in the track list.
3. Click **♫ Écouter Original / Ajusté (A/B)** and **Préparer l’aperçu ajusté**. If the levels are close, or boost would violate peak headroom, the UI should refuse a needless B.
4. For an eligible song, switch A ↔ B while the music plays and verify the timeline returns to the same point without a full restart.
5. Inspect B's file and JSON under `ab_previews`, ensure original master and reference are unchanged. Check independently measured True Peak ≤ −1.0 dBTP.
6. Click ♥ and verify only the local manifest changes to approved. It must NOT replace, rename or re-export the master.
7. Run `python -m unittest discover -s tests -p "test_album_ab_preview_v0256.py"` and previous v0.25.x tests.
8. Test dialog close while render is running: it must block closing rather than destroy an active QThread.

This draft PR is stacked on v0.25.5 (#19); the tests are authored but have not been executed on the user's Windows PySide6/FFmpeg environment. Validation required before merge.
