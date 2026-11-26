# FRANKENSTEM v0.27.2 — Native Live Engine timeout vs crash, non-blocking buffers

## User-observed symptom

The Live Stem Lab window (v0.27.0 title, later using v0.27.1 code) initially stayed disabled while JUCE loaded, then displayed:

> Impossible de lancer JUCE : Process crashed

The **v0.27.1 watchdog calls `QProcess.kill()` after 12 seconds**, and Qt reports that forced termination as `Crashed`. Therefore the screenshot **cannot distinguish an actual native crash** from the app's own watchdog kill. The generic "rebuild" guidance hid the causal startup phase.

## v0.27.2 fixes

1. **Truthful error reporting**: `_forced_timeout` is set *before* killing the child process. Subsequent Qt `errorOccurred(Crashed)` and `finished` events cannot overwrite the timeout warning. Actual native crashes still show the exit status, last startup phase and available stderr.
2. **Independent 15-second per-phase watchdog**: every native progress report restarts the watchdog. The Live Lab is not killed merely because many valid stems require some startup time.
3. **Non-blocking per-stem read-ahead**: the JUCE `BufferingAudioSource` now uses `prefillBufferOnPrepareToPlay=false`. The old value `true` could cause serial waits for disk buffers across many stems during audio device start. Streaming buffers are populated by the background `TimeSliceThread` instead. This is a plausible cause of the delayed timeout, **not yet confirmed on this user's Windows device**.
4. **Specific startup progress**: JUCE reports `Opening stem i/N`, `Opening JUCE output device`, `Attaching streaming audio source`, and `Starting JUCE audio callback`.
5. **Native checkpoint markers** on stderr before/after `player.setSource` and `devices.addAudioCallback`; they identify exactly where initialization stalls, without logging in the real-time audio callback.
6. **Clean ownership**: detach audio device callback and AudioSourcePlayer before stopping disk read-ahead. Avoid extra releaseResources calls after AudioSourcePlayer teardown.
7. The existing Offline `mastering-host`, all personal stems, original masters, export pipeline and QC checks remain unaffected. No preview WAV generation is introduced.

## Windows test — IMPORTANT: rebuild required

```powershell
git fetch origin
git switch -c test-v0272 --track origin/fix/v0.27.2-live-engine-timeout-vs-crash-buffering

cmake -S native -B native/build -G "Visual Studio 17 2022" -A x64
cmake --build native/build --config Release --target frankenstem-live
python scripts/desktop.py
```

Ensure the local branch is clean or stash committed modifications before switching.

### Direct native diagnostic

If Live FX still fails, run this **in your local project root**, adjusting the WAV paths to two aligned stems:

```powershell
$exe = ".\native\build\frankenstem-live_artefacts\Release\frankenstem-live.exe"
& $exe --probe
& $exe --stems "C:\path\to\Lead Vocals.wav" "C:\path\to\Bass.wav"
```

The direct player starts and emits JSON progress/ready to stdout; type `{"cmd":"quit"}` and Enter to exit. Standard error will print the last native checkpoint. **If a crash occurs**, capture the last `[LIVE STARTUP]` marker, Windows exit code and whether `--probe` succeeded. If all stem files work in pairs but a big album fails, record how many stems the problem occurs with.

### Expected results

- Fast startup displays `⚡ LIVE · JUCE` and enables Play.
- A genuine driver/native crash displays a crash message and last reported stage. A forced watchdog timeout explicitly says **FRANKENSTEM killed an unresponsive process**, which is **not a confirmed native crash**.
- Closing Live FX releases device, and no WAV files are created for UI adjustments.

## Limitations

This native code is in a **draft PR**, not compiled/executed on the user's Windows 11 x64 audio device by the assistant. Delayed silence while read-ahead warms up could occur after moving to non-blocking initialisation. If playback starts before buffers fill, the next phase should add explicit asynchronous warm-up readiness (without blocking the audio thread).

Structural regression tests are included; actual device playback, clipping and thread/teardown behavior require testing on the Windows machine.
