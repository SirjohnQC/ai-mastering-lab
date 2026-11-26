# FRANKENSTEM v0.26.5 — Stem Surgery (selective pre-mix saturation)

## Name
The desktop window and Auto Studio heading now show **FRANKENSTEM** (with AI Mastering Lab retained as the technology/product subtitle). This is a working name, not a GitHub repository rename.

## Reasoning
AI-generated vocals may sometimes benefit from gentle harmonics, but broad saturation of a **finished master** also distorts otherwise acceptable drums, cymbals or other sources. The album workflow already loads separate WAV stems, so v0.26.5 introduces an **explicit optional stem-level stage before the three candidate premixes**.

## Album Mode workflow

1. Import a folder of WAV stems for a song.
2. Click **⚡ FX Stems** on that song's card.
3. The **FRANKENSTEM · Stem Surgery** dialog lists each real source stem, its filename/category, an **unchecked** enable box, and a conservative proposed style/Drive/Wet. These are **category heuristics, not AI audio-artifact diagnosis**.
4. Optionally click **Pré-sélectionner voix et basse** as a shortcut. You must still review and confirm the dialog. Drums, cymbals and unknown stems are never automatically selected.
5. Click OK to approve your selected per-stem treatments (Tape / Tube / Soft Clip). Changing settings marks the song **waiting**, invalidates the old QC status and requires re-running Auto Produce Album; it does not delete an older master WAV from disk.
6. The album pipeline makes one locally cached **wet print per selected stem** with the same sample count, channels and sample rate. The originals are untouched. The normal mixer then uses each prepared wet print at the corresponding stem index for **all three** Balanced / Vocal Focus / Punchy candidates, and the selected result proceeds through the existing technical master / QC pipeline.
7. Stem choices and resulting wet print metadata live in the ignored local project/album output folders. Reuse checks include the exact selected settings, so a changed FX selection cannot silently reuse the previous master.

## Engine constraints

- Mono and stereo stems supported with oversampled 4× saturator processing. File duration and channel count must remain identical.
- A prospective saturated stem that would hard-clip is **rejected** rather than silently clipping input/output values; lower the Drive/Wet setting or bypass that stem.
- The final **mixed and mastered WAV** still undergoes the existing FFmpeg LUFS / True Peak QC. Stem-level saturation does not constitute a QC-pass on its own.
- **No per-stem processing by default.** Human opt-in is required. Suggestions only recognize filenames/categories; there is **no reliable trained detector** that automatically repairs AI voice artifacts.
- Cache keys include the local source signature and settings. Source WAVs, stems, original masters and album reference stay local, outside GitHub.

## Windows testing

1. Switch to `feature/v0.26.5-frankenstem-selective-saturation` and run `python scripts/desktop.py`.
2. Confirm the title shows FRANKENSTEM and Album Mode displays **⚡ FX Stems** on stem-folder songs (not on already mixed stereo WAVs).
3. Open one song's Stem Surgery window; all checkboxes should initially be disabled. Use the **Pré-sélectionner voix et basse** shortcut, confirm drums still unchecked.
4. Check a vocal stem. Keep Tape, Drive about 0.5–0.6, Wet 10–12%; approve. The song must become **waiting** and ask for a new production.
5. Run Auto Produce Album. Confirm its produced mix candidates use wet prints for only approved stems, while unselected stems are untouched. The final QC report must be generated as usual.
6. Change saturation settings and rerun. Cached masters must not be reused under different approved FX.
7. Leave all settings unchecked on a different song. That song should follow the old dry premix behavior with no saturation rendering.
8. Inspect the `sound/output/album_studio` cache only on the local machine; confirm originals, other stems and reference WAV remain unchanged.
9. Run `python -m unittest discover -s tests -p "test_frankenstem_selective_saturation_v0265.py"` and `test_album_saturation_v0264.py`, then older album tests.

## Important limitations

This first stage is a **manual-approved selection of category-based suggestions**, not autonomous diagnosis of voice defects or intelligent time-selective repair. The tool currently produces three **full-song** premix candidates; applying a stem FX changes that stem throughout the song. Segment-specific processing, previewing individual wet/dry stems in the same player and artistically smarter FX selection are future enhancements.

Tests are committed but have **not been run on the user's Windows PySide6/FFmpeg installation**. This remains a draft PR pending real stem-based acceptance.
