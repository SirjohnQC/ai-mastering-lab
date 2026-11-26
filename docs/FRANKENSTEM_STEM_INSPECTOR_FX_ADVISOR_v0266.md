# FRANKENSTEM v0.26.6 — Stem Inspector + FX Advisor

## What changed

Album Mode → on a stem-folder song → **⚡ FX Stems** → **FRANKENSTEM · Stem Surgery**.

1. **⌕ Inspecter les stems · FX Advisor** performs read-only DSP analysis in a background worker for each stem, using the existing `stem_inspector.inspect_audio_file` window analysis. It measures crest factor, high-frequency energy above 10 kHz, and near-full-scale samples. It can say **Essai possible** or **Bypass conseillé**, with the numerical evidence and a reason.
2. No claim of detecting AI provenance, AI-generated defects, or a guaranteed sonic improvement. The advisor is a conservative heuristic. Drums and unknown categories default to bypass; clipping indications and elevated HF also block the recommendation. Nothing is applied automatically.
3. **✓ Pré-sélectionner les essais recommandés par mesures** becomes available *only after* a completed inspection. It checks only recommended candidates, not the drums/unknown/unsafe stems. The user must still confirm **OK**; cancellation leaves the project unchanged.
4. Each stem has **♫ Écouter Dry / Wet**. A QThread renders a separate local oversampled saturation preview using the current style, Drive and Wet settings, then RMS-matches B to A (±0.2 dB). A source-peak overflow rejects the preview rather than clipping. Dry is always the original untouched source.
5. Dry and Wet use distinct preloaded QMediaPlayers, a single transport, visible active A/B highlighting and seek-based transition. Qt may still have short device/backend latency: **not sample-accurate crossfade**.
6. Stem FX approvals retain the v0.26.5 behavior: the original WAVs remain untouched; approved wet prints are consumed by all three premix candidates on the next Auto Produce; changing a selection marks that song `waiting` so its older QC master cannot be mistaken for a new result.
7. The preview WAVs and JSON cache live under ignored `sound/output/album_studio/stem_fx_previews` and should remain *local only*. This PR is code, tests and docs only.

## What we did not build yet

- Autonomous AI artifact diagnosis, spectral de-essing, passage-specific repair, automatic Pro-Q/Pro-C/VST chain choice, or stem-context preview inside the full mix.
- The Dry/Wet preview compares the **individual stem** at approximate matched RMS, not final integrated LUFS or final mastered True Peak. The full premix/master pipeline continues running final QC.
- A measured recommendation is *not* an approval and is not stored as an active effect until the user confirms the dialog.

## Windows acceptance checklist

1. Checkout `feature/v0.26.6-stem-inspector-fx-advisor` and run `python scripts/desktop.py`.
2. Open **Bloom** or another song with separate stems. Click **⚡ FX Stems**.
3. Click **Inspecter les stems**. Wait for a per-file measured summary; check vocal, bass and drums advice. It must not pre-check anything.
4. Click **Pré-sélectionner les essais recommandés par mesures**. Verify drums/unsafe stems stay off.
5. Pick a voice stem. Leave Tape at Drive 0.5–0.6, Wet 10–12%, click **Écouter Dry / Wet**. After Wet renders, switch A↔B while playing, checking the active version and approximate play position.
6. Close Dry/Wet. Click Cancel in Stem Surgery: no effect should be applied. Open again, approve only the desired stems and run Auto Produce Album.
7. Confirm original source WAVs remain unchanged, premixes reference the explicitly approved wet prints, and the final master gets its normal QC.
8. Run `python -m unittest discover -s tests -p "test_frankenstem_inspector_fx_advisor_v0266.py"` along with v0.26.5 / v0.26.4 regression tests.
9. Recheck bilingual interface text; the new Stem Surgery strings are currently mostly French with technical English labels. Full localization remains follow-up work.

## Status

Draft PR, not yet tested against the user's Windows/PySide6/FFmpeg setup. Requires local end-to-end validation before merging. The underlying inspector is deterministic, not an ML classifier, and we should not claim it recognizes 'good' or 'bad' AI music.
