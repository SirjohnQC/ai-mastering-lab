# v0.23.8 — Compression Activity Inspector

## Why
Gentle may barely alter a song despite global PCM peaks exceeding its threshold. A source with -3 dBFS peak and -9 dB Pro-C 3 threshold can still have only fleeting excursions. v0.23.7 could not distinguish those from sustained high-level material.

## What it measures
- Streams the **local 48 kHz stereo Original WAV** in 10 ms windows, for each of the two per-song Pro-C 3 read-back physical thresholds (Gentle/Firm).
- Calculates percentage of windows whose **sample peak** exceeds the read-back threshold.
- Separately calculates percentage of windows whose **window RMS** exceeds threshold.
- Measures the longest consecutive run of each category, especially sustained RMS above threshold.
- Categorizes as below threshold / brief peaks / intermittent input / sustained input, without claiming actual compressor operation.
- Compares observations to the already measured processed WAV RMS difference, and displays a cautious explanation in **Comparer**, under the previous Gentle explainer.
- Measurements are cached locally under `settings/pro_c3_unified_diagnostics.json`, diagnostics schema 4. Existing JUCE audio preview cache remains valid; **no rerender is necessary**.
- No plugin parameter mutation, no audio upload, no automatic compression approval. Existing heart gate and 9-track player unchanged.

## Interpretation and limitations
Threshold crossing is **NOT** FabFilter's gain-reduction telemetry. The VST detector may use its own weighting, look-ahead, attack/release, knee or stereo linking and may not respond in direct proportion to either statistic. Even sustained RMS crossing is a reason to *investigate* unchanged audio, not proof of bypass or error. The analyzer also cannot prove that music is already compressed from crest factor or global peak alone.

## Acceptance tests (Windows)
1. Run `git fetch origin` and switch to `feature/v0.23.8-compression-activity-inspector`. Launch `python scripts/desktop.py`.
2. Open Comparer for an unchanged song. Wait for the diagnostics to recompute once; Pro-C 3 WAV renders should come from their existing cache.
3. Select Balanced + Gentle: see the new **Activité source au seuil Gentle** line with peak/RMS percentages and sustained RMS duration.
4. Try Firm and another mix. Numbers should reflect the active variant's verified physical threshold; never the normalized 0.70/0.85 grid coordinate.
5. On a song with strong but extremely short peaks, peak percentage may be nonzero even if RMS percentage is zero, helping explain a very subtle Gentle.
6. Confirm the waveform markers, continuous playback, manual heart mastering selection and audio cache still behave the same.
7. Run `python -m unittest discover -s tests -p "test_compression_activity_v0238.py"`. Then run previous versions' test suites.

## Safety
All audio, renders, stems, diagnostics and settings are local. The PR contains code/docs/tests only. Test the Windows JUCE/Qt behavior before merging. The previous stacked PRs (#1–#6) are prerequisites.
