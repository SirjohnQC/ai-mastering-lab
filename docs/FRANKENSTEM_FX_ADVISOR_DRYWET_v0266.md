# FRANKENSTEM v0.26.6 — Stem Inspector + FX Advisor + Dry/Wet audition

## User-facing workflow
Open **Album Mode**, import a song's stem folder, then click **⚡ FX Stems** on its card.

The new **Stem Inspector + FX Advisor** dialog displays individual WAV stems and a button **✦ Analyser les stems et suggérer**. The local worker samples five short windows from each stem to measure sampled peak, crest factor, near-clipping and proportion of energy above 8 kHz. It uses conservative, explainable rules to show either:
- **✦ Écoute suggérée**: a possible gentle Tape/Tube setting worth auditioning, usually on voices or bass if no warning signs were detected.
- **✓ Garder Dry par défaut**: high-frequency density, potential clipping, flattened dynamics, drums or unknown sources make automatic saturation less sensible.

These are NOT machine-learned AI-artifact detections. Measurements sample part of the audio and cannot establish that saturation will sound better.

## New Dry / Wet button
Every stem row contains **♫ Dry / Wet** even before the user approves any FX.

1. It prepares a local, bounded **up to 18-second segment** from the same source WAV (an active region, chosen from five samples).
2. A is the untouched dry segment. B is that same segment after the row's selected Tape, Tube or Soft Clip settings.
3. B gets **conservative RMS matching to A** to reduce volume bias; the preview is rejected if keeping the level matched would dangerously approach clipping. This is NOT a full-song LUFS or True Peak certified master.
4. The dialog has two WAV players preloaded once, one shared Play/Pause button, a visible **A · DRY / B · WET** status and source buttons. Switching does not reload audio from disk. True sample-perfect seamless playback is not guaranteed by Qt Multimedia.
5. Preview audio and JSON remain under the user's ignored local `sound/output/album_studio/stem_fx_previews/` cache. Source WAV is never modified.
6. The operator must still explicitly check the desired stem(s) and click OK to approve their settings. No analysis or audition automatically approves anything.

Changing the approved settings continues to mark the album song as `waiting`, without removing previously rendered masters from disk, and the next **Auto Produce Album** uses the approved prepared wet prints in all three premixes before master QC (from v0.26.5).

## Safety
- No automatic treatment on drums, cymbals, unknown tracks or even voices/bass by default.
- Unknown, corrupt, silent, clipped or unsafe stems are marked for review or blocked from playback.
- Mono and stereo WAV stem audition supported.
- Heavy DSP/preparation runs on a Qt worker thread to keep the window responsive; closing while audio rendering is active is blocked to avoid destroying a live QThread.
- No files, recordings, stems, masters, private references or local user settings uploaded to GitHub.

## Windows acceptance
1. Switch to `feature/v0.26.6-frankenstem-fx-advisor-drywet`, run `python scripts/desktop.py`.
2. Album Mode → choose a song with WAV stems → **⚡ FX Stems**.
3. Click **Analyser les stems et suggérer**. Verify that advice appears for each vocal, guitar, bass and drum stem, with numeric evidence. Verify that all *previously-unapproved* stems remain unchecked.
4. Click **♫ Dry / Wet** next to a vocal stem, render Tape Drive 0.6 / Wet 12%. Compare A and B near the same 18-second passage while observing the obvious active version label.
5. Switch its saturation to Tube and change Drive/Wet. Preview should yield a distinct cached B. Ensure no audio source WAV changed.
6. Do not check the box and exit with OK: the stem should remain unprocessed. Check a vocal stem, approve and run Auto Produce Album; verify the original QC pipeline still runs and only approved stems receive wet prints.
7. Inspect local preview JSON and the source file mtime/hash; source must be untouched.
8. Run `python -m unittest discover -s tests -p "test_frankenstem_fx_advisor_drywet_v0266.py"` and the previous v0.26.5 stem processing tests.

## Deliberate limitations
There is no automatic repair of AI-generated vocal flaws, segment-specific FX application or machine-learned audio quality score. The preview uses approximate RMS matching, not psychoacoustic loudness matching. This release also does not introduce Pro-Q, Pro-C, Soothe, or other VST plugin processing to the automatically generated stem FX suggestions.

The code and tests are written in this draft branch, but an end-to-end run on Windows / PySide6 / FFmpeg is still required before merging. The PR is stacked on v0.26.5 (#28).
