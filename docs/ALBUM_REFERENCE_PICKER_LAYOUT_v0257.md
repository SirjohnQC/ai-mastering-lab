# AI Mastering Lab v0.25.7 — Album reference selection & usable layout

## Bug report / diagnosis

The Album Mode reference dropdown opened, but its unmastered song/stems entries were explicitly set to disabled in the model. Users with a fresh album of stems could not select any song even for a future reference. The saved choice was also restored only if the song already had QC-pass status.

Four loaded stems folders with zero mastered WAVs produced a long analysis diagnostic block, leaving almost no room for album cards. The A/B action was disabled, correctly, but without a clear explanation of the next step.

## Improvements

- **Reference selection is no longer QC-gated.** A stem-folder song may be selected now, saved in the local project, and restored after re-opening. Entries still indicate **à produire** until a QC master is available.
- **Analysis remains QC-gated.** The user can choose a song that is not ready, but Album Intelligence will not pretend to measure its future master. A clear status says the song must first be produced.
- **Explicit reference mode**: choosing a standalone WAV activates the external WAV; choosing a song in the dropdown activates that album song. The last active choice is stored as `album_reference_mode` in local `settings/album_project.json`. Existing projects with an external reference default to that reference until the user selects another.
- If an album reference song already has a QC-pass master WAV, the production workflow can pass that master as the *weak* standalone reference to its premix selection. If that song is not yet ready, the pipeline conservatively relies on the existing inspiration/preferences and no nonexistent audio is used.
- **Album tracks list gets at least 280 px vertical space**. The long line-by-line Album Intelligence results are initially collapsed to 88 px, with an explicit button to expand. When no mastered tracks exist, a single short message replaces four redundant QC diagnostics.
- The prior analysis summary isn't overwritten by an unrelated dropdown rebuild.
- The external WAV stays outside the album inventory; drag-and-drop order, QC association and master file storage are untouched.

## Windows test

1. Checkout `fix/v0.25.7-album-reference-picker-layout` and run `python scripts/desktop.py`.
2. Import four stems folders and select any waiting song from the **Alternative : master QC déjà dans l’album** dropdown. The selected title must remain visible rather than snapping back to `Choisir une chanson`.
3. Reopen Album Mode or restart the app and confirm the chosen reference was persisted (no QC pass needed yet).
4. Verify **Analyser la cohérence** stays disabled until there is a real QC-pass reference master plus at least one QC-pass song. Do not confuse selection with eligibility for audio comparison.
5. Choose a separate external reference WAV again. It should take priority until a song is newly selected in the dropdown.
6. Verify all four song cards are easier to see, and detailed results can be expanded only when useful.
7. After producing masters, choose a QC-passed song and run Album Intelligence; the report should persist on screen after the async worker finishes.
8. Run `python -m unittest discover -s tests -p "test_album_reference_picker_layout_v0257.py"` plus previous album regression tests.

### Limitations

The alternative album reference is a **future source selection**, not a stems reference audio for early mix processing. A song with unrendered stems cannot be used for meaningful audio guidance until its master exists. The standalone WAV continues to work immediately for reference-aware premix candidate selection and final WAV comparison. No automatic EQ or processing was added.

Code/tests/docs only are committed. Private stems, reference WAVs, masters, QC data, caches and settings remain local. Tests are written but require acceptance on Windows/PySide6 before merging.
