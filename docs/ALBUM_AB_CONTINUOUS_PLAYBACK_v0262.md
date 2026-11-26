# AI Mastering Lab v0.26.2 — Preloaded A/B and visible active version

## User bug

The v0.26.1 A/B dialog used **one QMediaPlayer** and called `setSource()` on every A/B click. Qt Multimedia unloaded the previous WAV and reloaded the new file, **stopping music**. The button style also did not show which version was actually playing.

## Fix

- **Two QMediaPlayers with two QAudioOutputs.** A (the QC-passed original master) loads when the dialog opens. B (Tonal Match or Creative preview) is loaded **once**, only after its rendered WAV has passed loudness and true-peak checks.
- **Single visible transport** remains. Pressing A or B seeks the inactive player to the active player's current position; it does *not* call `setSource()` again.
- During playback, the incoming player starts **muted**. Only once it reports `PlayingState` does the app switch which output is audible and pause the previous player. This is a handoff instead of a source reload. Fast repeat clicks cancel pending handoffs.
- The **active A/B button becomes violet with a bright border** and the dialog displays **♫ EN ÉCOUTE : A · ORIGINAL** or **♫ EN ÉCOUTE : B · TONAL MATCH / CREATIVE WARM / PRESENCE / AIR**. Button accessibility names also say which version is active.
- A disabled B remains visibly unavailable until the actual preview file has loaded; choosing a new Creative mode returns to A and unloads the old B (without touching the original).
- Both players stop on dialog close. All source WAVs, mastered WAVs, QC sidecars and approval semantics remain untouched.

## Practical caveat

Two independently decoded QMediaPlayers **minimize the gap** compared with reloading one source, but Qt Multimedia is not a sample-accurate DSP switcher. The resulting transition may still have a very short seek/decoder delay depending on Windows' audio backend, device and WAV length. This is **not yet guaranteed sample-perfect / gapless** playback. A future low-level audio-buffered transport would be needed for that.

## Windows acceptance

1. Switch to `fix/v0.26.2-ab-continuous-playback-active-indicator` and start `python scripts/desktop.py`.
2. In Album Mode, analyze a QC-passed master, click its **♫ A/B**, and render a Creative B (e.g. Warm) or a valid Tonal Match.
3. Wait for **B · Tonal Match** to become enabled. Play A and press B **while music is playing**. The WAV should continue around the same section rather than stop/restart at 0:00. The bright violet selection and status text should switch to **B** after playback starts.
4. Press A and verify the active indicator returns to **A**, with music staying near the same timestamp.
5. Try rapid A/B toggling and switching from Warm to Air. The old B should become unavailable until a new preview is loaded. Ensure only one output is audible.
6. Pause, switch versions, resume: time should remain aligned. Closing A/B stops both player streams.
7. Run `python -m unittest discover -s tests -p "test_album_ab_continuous_playback_v0262.py"`, then the earlier Album A/B regression tests.

This is a draft PR stacked on v0.26.1 (#24). Automated structural tests are included; Windows/PySide6 end-to-end audio needs user verification. No personal audio or settings are committed to GitHub.
