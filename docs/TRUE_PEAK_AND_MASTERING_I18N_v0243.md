# v0.24.3 — True Peak Safety + Mastering Report FR/EN

## Changes

**True Peak integrity:** the user-facing export ceiling remains **−1.0 dBTP**. FFmpeg loudnorm second-pass now uses a conservative **−1.2 dBTP internal rendering ceiling** for 0.2 dB of measurement/encoding margin. The final PCM24 WAV is independently measured **again after encoding**. If actual measured true peak is **above −1.0 dBTP**, QC fails (previously allowed 0.2 dB above ceiling) and the output is kept as a QC-review file rather than a successful master.

The internal -1.2 is a safety margin, **not** a Spotify requirement. On a specific source loudnorm may change other level statistics; acceptance still requires validating both measured LUFS and TP. No automatic resampling/retry or overwrite of existing releases.

**FR/EN reports:** the existing persistent language preference now determines the Mastering QC summary and the release preflight text, including common warnings. Switching language re-renders the **UI text only** from the existing metrics; no FFmpeg rerender, no WAV changes. Existing diagnostic JSON remains language-neutral. Legacy worker progress strings and some Advanced dialogs may still appear in French and require later translation.

## Windows acceptance steps

1. Fetch branch `feature/v0.24.3-truepeak-and-mastering-i18n`; run `python scripts/desktop.py`.
2. Open existing `Voicemail From 2004` master and switch French / English: the result and preflight report should change without audio processing.
3. Start a **new** Auto Master using the same input. The earlier master stays intact. Check actual measured true peak is **≤ −1.0 dBTP**, preferably around −1.2, and loudness still near −14 LUFS.
4. Confirm the new preflight has no `True peak supérieur à −1 dBTP` note. If any post-encode output still exceeds ceiling, the operation should be marked **QC review**, never `QC pass`.
5. Change languages after the report is displayed: all displayed QC measurements should stay identical, only language changes.
6. Run `python -m unittest discover -s tests -p "test_truepeak_mastering_i18n_v0243.py"`.
7. Check that no stems/audio/session WAVs are staged or pushed. Only code, tests and docs belong in the public repository.

## Limitations

Manual critical listening, album consistency, metadata and distribution decisions remain outside the technical QC pass. Existing already-rendered WAV files are **not** retroactively fixed or deleted. This PR is stacked on v0.24.2 / PR #11; validate under Windows FFmpeg/PySide6 before merging to main.
