# FRANKENSTEM v0.27.0 — JUCE Live Stem Engine (first milestone)

## Goal

Replace **preview WAV generation** with a real-time audio stream for **stem audition**. Preserve the existing offline 3-premix/master/export pipeline until the new player is verified.

This is an *experimental native JUCE engine*, not yet a complete DAW. Existing `mastering-host` VST3 inspection/render executable is left untouched. No external model service or internet is needed during playback.

## Architecture

- New C++ JUCE executable: `native/src/live_stems.cpp`, CMake target `frankenstem-live`.
- The executable opens **2–32 mono/stereo WAV stems**, requires a common sample rate and a common length (±50 ms), then connects a multistem `AudioSource` to the Windows default audio device using `AudioDeviceManager` + `AudioSourcePlayer`.
- Each stem uses a JUCE `BufferingAudioSource` with a `TimeSliceThread` for **disk read-ahead**. The audio callback sums stems and applies native Tape/Tube/Soft Clip digital transfer curves in memory. Per-stem wet mix, drive, gain, enable, mute and solo are stored as atomics; user commands do not parse JSON inside the audio callback.
- The playback-device sample rate is configured to the original stem rate or the engine refuses playback, rather than silently changing pitch. Conservative monitor gain and an emergency ceiling guard the listening output. **This monitor audio is NOT a mastering QC or sample-accurate export.**
- A JSON-lines command protocol over stdin/stdout accepts `play`, `pause`, `stop`, `seek`, `set`, `status`, `quit`. The command channel is separate from the real-time audio callback.
- `src/mastering_lab/live_stem_ui.py` uses **QProcess** to launch the executable, then sends commands as the user changes Drive, Wet, saturation character, Bypass, Mute or Solo. No preview WAV and no repeated external FFmpeg render are created during adjustments.
- **Album Mode → ▶ Live FX** on each stem song opens the new `Live Stem Lab`. The GUI offers shared play/pause/stop/seek and a stem picker, with per-stem controls. The user can explicitly click **Approuver FX pour Auto Produce** to persist the selected saturation parameters via the existing v0.26.5 stem pipeline. Closing/Cancel does not approve anything. Approved FX invalidate that song's previous QC status until re-export, but never delete a source or master.

## Windows build (Visual Studio 2022, x64)

From repo root:

```powershell
cmake -S native -B native/build -G "Visual Studio 17 2022" -A x64
cmake --build native/build --config Release --target frankenstem-live
```

You can still build `mastering-host` separately as before. The new executable is normally located at `native/build/frankenstem-live_artefacts/Release/frankenstem-live.exe` (verify actual path after build).

Then launch desktop:

```powershell
python scripts/desktop.py
```

Album Mode → select a stem-folder song → **▶ Live FX**. Start with all effects **OFF**, press Play, select **Lead Vocals**, enable FX, move Drive and Wet in real time. Toggle Solo, Mute and Bypass. The playback should not restart and the app should generate **no new preview WAVs** from these changes.

Use **✓ Approuver FX pour Auto Produce** only if you want those per-stem saturation settings used in a new full premix/master job. The offline pipeline will still render its normal 3 candidates and output QC files (this is intentional final production, NOT preview spam).

## Acceptance checklist

1. Run `python -m unittest discover -s tests -p "test_live_stem_engine_v0270.py"` (cross-platform structural smoke checks).
2. Compile the native target with MSVC. Confirm launch with two sample-rate-matched WAV stems; mismatched lengths/rates should fail with a readable error.
3. Open Live Lab on a real album song, Play → Solo lead vocal → FX ON → move Drive/Wet/Tube/Tape. Verify that the time counter advances without restarting or adding preview WAVs, with a clear Mute/Solo/Bypass state.
4. Pause, seek halfway, resume; exit and reopen. Confirm the audio device is released.
5. Cancel the dialog: no project settings or original WAVs modified. Approve FX: song status changes to waiting; next Auto Produce uses prior v0.26.5 safe offline processing.
6. Full mastering QC remains unchanged and still independently verifies the final WAV.

## Known limitations / engineering next steps

- **Native JUCE target and real Windows audio device have NOT been compiled or tested in the assistant environment**. This PR stays draft until the user's Windows smoke test passes. Device setup/latency is backend-dependent.
- This **first milestone is real-time saturation + stereo mixing**, not real-time FabFilter VST3 hosting or a complete A/B/C mastering chain. No Pro-Q or Pro-C is connected to the new live graph yet.
- A stem can be soloed/muted and auditioned with/without saturation; gain is controllable through the engine protocol, but an on-screen gain slider and reference-matched comparison come in later phases.
- No plugin latency compensation, time-stretch, resampling, per-track EQ, or dynamic automation yet.
- Playback transport and atomic FX controls are experimental, with buffer-level timing rather than sample-accurate automation. Monitoring gain/ceiling differ from final export; do not mix/master solely by reference to their apparent loudness.
- JSON-lines commands are local IPC, not authentication or network endpoints. The engine never writes audio files; its stdout contains status JSON only.
- Avoid committing personal audio, settings, QC reports or reference tracks.

## Next native milestones

1. Confirm reliable callback, audio-device stability and seek/transport under Windows.
2. Add live parametric EQ DSP and metering to the same audio graph (still zero preview WAVs).
3. Host existing detected VST3 effects with latency compensation, crash isolation/fallback and parameter mapping.
4. Link the same live DSP graph to a deterministic offline render/export path; add A/B/C snapshots and loudness-matched compare.
