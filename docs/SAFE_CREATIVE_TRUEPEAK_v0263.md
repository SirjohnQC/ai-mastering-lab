# v0.26.3 — Adaptive True Peak Protection for Creative B

## User report
Creative Presence exceeded the **−1 dBTP** ceiling even though A was QC-pass. A/B properly refused unsafe B, but the old UI looked like a generic crash and forced the user to change presets.

## Fix
- Retain the exact previously approved A master (no writes or overwrites).
- Try the chosen EQ at 100% strength first; if B's independently measured True Peak exceeds −1 dBTP, retry progressively gentler **75%, 50% and 30%** strengths.
- For **each** attempt, render EQ, measure LUFS, apply bounded level matching relative to A, re-render as 24-bit PCM and independently re-check true peak and audio metadata. A hard limiter is **not** secretly added to force success.
- Accept the **first** candidate passing both the −1 dBTP ceiling and ±0.25 LU relative loudness threshold. Store the actual final EQ gains and **eq_strength** in the local B manifest; the old policy cache key has changed so prior invalid previews are not reused.
- If all attempts fail, display a clear recommendation to keep A or try a different creative style. QC is never overridden.
- The B selector button now shows **B · Creative Presence / Warm / Air** rather than inaccurately saying **B · Tonal Match** for every mode.

## Saturation roadmap
A separate future opt-in **Creative Saturation** stage (Tape / Tube / Soft Clip) may be added before the final true-peak limiter/QC, including carefully bounded drive, wet/dry mix, loudness-matched A/B, and artifacts/harshness listening checks for AI-generated stems. Saturation is not in v0.26.3. The workflow should never saturate all songs by default.

## Windows testing
1. Fetch `fix/v0.26.3-safe-creative-truepeak-fallback` and launch `python scripts/desktop.py`.
2. Load the already QC-mastered Kids in Love and a reference WAV; analyze album; click its A/B; select Creative Presence.
3. Prepare B. If normal intensity exceeds True Peak, the pipeline should automatically try gentler EQ intensities. The result, when safe, must say **intensité adaptée 75% / 50% / 30%**, display actual EQ gains, and list final TP below or equal to −1 dBTP.
4. If no safe B exists, the UI refuses the preview and A remains available and untouched, without suggesting a false QC pass.
5. Repeat with Warm and Air, and test A/B switch mid-song and active A/B indicator (from v0.26.2).
6. Run `python -m unittest discover -s tests -p "test_safe_creative_truepeak_v0263.py"` plus earlier v0.26.x tests.

Tests authored in GitHub, but not executed on the user's Windows/PySide6+FFmpeg system. This PR is stacked on v0.26.2 (#25) and remains draft until accepted. All WAVs, stems, masters, references, JSON runtime reports and settings remain local.
