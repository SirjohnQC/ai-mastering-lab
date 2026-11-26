# FRANKENSTEM v0.27.1 — Live Engine Startup Preflight + Hang Diagnostics

## Bug reported

The Live Stem Lab dialog would remain on **« Initialisation du moteur JUCE… »** with all buttons disabled indefinitely. The v0.27.0 interface did not enforce any startup timeout; if the native JUCE process hung during WAV decoding, audio-device setup or buffer preparation before emitting `ready`, the user received no further information. This change prevents that indefinite waiting and surfaces the last known phase. It is not proof that the underlying Windows audio device issue is solved.

## Fix

- New native `frankenstem-live --probe` command quickly attempts to initialize the default JUCE audio output device **without loading any stems**, reports its device name and rate, releases the device and exits.
- FRANKENSTEM now runs that probe during a **bounded startup splash screen** before the main desktop window opens. The preflight has a **five-second timeout** and reports success/failure in the desktop status bar. Failure leaves normal Auto Produce and mastering available.
- Song-specific Live FX loading still occurs when a song is chosen: JUCE emits progress lines as it opens stems, initializes the output device and prepares streaming buffers.
- Live Stem Lab now has a **12-second watchdog**. No reply? It terminates the stuck subprocess and displays the last initialization phase. Startup failures and early process exit get meaningful messages rather than leaving disabled buttons on « Initialisation… ».
- The native device probe and live player are two separate subprocesses, so the probe does not keep the audio interface reserved while the user works elsewhere.
- No source audio, stem, master, cache or QC outcome is modified by startup.

## Windows installation / smoke test

From the project root, after checking out `fix/v0.27.1-live-engine-startup-preflight-watchdog`, **recompile the new executable**; just updating Python is insufficient:

```powershell
cmake -S native -B native/build -G "Visual Studio 17 2022" -A x64
cmake --build native/build --config Release --target frankenstem-live
python scripts/desktop.py
```

1. On app launch, the FRANKENSTEM splash must display JUCE preflight and then allow the main window to open, whether JUCE succeeds or not.
2. Check the status bar for **JUCE prêt** with an output device name/rate, or a meaningful failure message.
3. In Album Studio, open a stem song → **▶ Live FX**. The status should progress through opening the stems, the audio output device and buffers until **⚡ LIVE**.
4. If it hangs, the Live FX dialog must show the **last phase** and stop the process after at most 12 seconds rather than waiting indefinitely. Capture the last phase, full terminal output and/or Windows Event Viewer crash code for further debugging.
5. If the host reports that the audio device cannot use the stems' sample rate, review the Windows audio output device settings (JUCE requires matching input WAV/device rates in this MVP).
6. Run `python -m unittest discover -s tests -p "test_live_engine_startup_v0271.py"` and the earlier v0.27.0 regression tests.

## Important caveats

- This PR is **draft** and not compiled/tested on the user's Windows/PySide6/FFmpeg/JUCE setup. The watchdog is a reliability guard, **not proof that a driver/device deadlock has been fixed**.
- Startup can preflight the **engine/device**, but cannot preload and synchronize the actual stems for every song until the user selects them. Song-specific disk read-ahead remains in Live FX.
- The startup probe may increase cold-launch time by up to five seconds if JUCE fails to respond; the splash and timeout make that wait bounded.
- The existing offline mastering host and QC/export paths are untouched.
