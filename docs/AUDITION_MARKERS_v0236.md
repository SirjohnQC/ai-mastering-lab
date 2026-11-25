# v0.23.6 — Review markers for compression audition

The existing Compare screen can now suggest **up to three moments worth listening to**, instead of requiring a full-song hunt to find where Gentle/Firm changes the mix.

## Scope

- Source-aligned 100 ms PCM measurements are obtained from the **existing local WAV files**, with no new JUCE renders and no file uploads.
- Only windows whose *Original* RMS is at least the source median are considered.
- Candidates are ranked by how much processed RMS differs from the quiet-window baseline, plus a modest peak-difference contribution.
- Only meaningful differences (score >= 0.30) qualify. The three highest-scoring windows are separated by at least 4 seconds and listed chronologically.
- Each button displays an approximate timestamp, with a 400 ms pre-roll. Clicking moves **all nine synchronized Qt players** to that point and starts the existing player if stopped. Switching Original/Gentle/Firm at that point keeps the shared transport.
- Buttons update with the selected mix and compression; Original shows none.
- A diagnostic cache schema bump to 3 causes the **analysis** to rerun once on existing renders. It does not invalidate the JUCE render cache.
- Audio and diagnostics remain under ignored local `settings/` directories; only code/docs/tests are committed.
- The explicit ♥ approval requirement remains unchanged.

## Limitations

These are **measured review positions**, not confirmed clipping, artifacts, or actual Pro-C 3 gain-reduction telemetry. Small differences may correctly yield no markers. Judgement still requires critical listening. The short-window metric is a proxy; it is not integrated LUFS, true peak, or a trained musical preference model.

## Windows acceptance

1. Switch to `feature/v0.23.6-audition-markers`, launch `python scripts/desktop.py`.
2. Open Comparer with a cached song and select Gentle/Firm. Under the waveform, confirm that zero to three time markers appear when measurable changes exist.
3. Click a timestamp; song should jump slightly before that moment and begin playing, using the same shared player. Listen to the passage; switch to Original and back. Neither change should recreate the song or restart at zero.
4. Try another mix and confirm markers change, then select Original and verify markers disappear.
5. Check session cache reuse; the six JUCE renders should not be recreated for unchanged source mixes.
6. Confirm ♥ remains required for any processed version to reach Mastering; no audio files were uploaded.
7. Run `python -m unittest discover -s tests -p "test_audition_markers_v0236.py"`, and ideally the tests for versions 0.23.2–0.23.5.

Real JUCE/Qt playback must be verified on Windows before merging. This change depends on the previous stacked draft PRs.
