# v0.25.3 — Standalone WAV album reference

## Workflow

1. Choose a separate stereo WAV using the new **Choisir WAV de référence** button in Album Mode. Do NOT add this WAV to the album's tracks. No sidecar QC report is needed for an inspiration/reference WAV.
2. Import the separate stems folders for each album song. Each folder is rendered into Balanced / Vocal Focus / Punchy premix WAVs. The reference's sampled spectral profile acts as a weak preference for local Hermes to choose among those three completed premixes, not a set of FX commands.
3. The selected premix is technically mastered into one finished WAV per song via the existing FFmpeg/QC pipeline. The standalone WAV is not mixed into any tracks, overwritten or uploaded.
4. Album Intelligence compares the final QC-passed mastered WAVs against the standalone reference, remeasuring its actual LUFS and true peak via local FFmpeg. The existing Advisor suggests checks by ear only.

## Limitations

The reference does not yet auto-adjust stem gain plans, master EQ or final mastering loudness. This is reference-aware premix selection and post-master comparison, not automatic replication. The separate Reference Learning inspiration library remains available for other workflows. The external album WAV takes precedence over Reference Learning for album premix selection.

The reference path is saved only in settings/album_project.json on the user's machine. Selecting/removing/changing it updates cache eligibility for stem masters. If the WAV is missing, Album Mode displays an error instead of silently using a different reference.

## Windows testing

1. Fetch feature/v0.25.3-external-wav-album-reference and run python scripts/desktop.py.
2. Select an external reference WAV via Album Mode's dedicated button. Verify the song count does not increase.
3. Add 2+ stems folders, then Auto Produce Album. Confirm the reference is mentioned as album_standalone_wav in album_ai_selection when Hermes succeeds.
4. Run Album Intelligence after technical QC. Confirm the standalone WAV is accepted without a .qc.json and all analyzed masters remain separate.
5. Change the reference and verify old stem selections are not reused incorrectly. Test a missing reference: the app must warn.
6. Run python -m unittest discover -s tests -p test_standalone_album_wav_reference_v0253.py, then earlier album tests.

All private WAV, sound, settings and QC reports must remain local. Draft PR pending Windows PySide6/FFmpeg acceptance.