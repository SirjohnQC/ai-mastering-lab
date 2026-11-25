# JUCE VST3 Host — experimental Phase 2

This is source code for a native Windows JUCE command-line host. It has **not** been compiled or exercised against licensed Windows plugins in this environment. Plugin compatibility is unknown until tested locally.

## Requirements
- Windows 11 x64
- Visual Studio 2022 with Desktop development with C++ workload
- CMake 3.22+ and Git
- Internet access during first CMake configure (JUCE fetched from GitHub)
- Installed and activated VST3 plugins

## Build (PowerShell in project root)
```powershell
cmake -S native -B native/build -G "Visual Studio 17 2022" -A x64
cmake --build native/build --config Release --target mastering-host
```

Executable usually: `native/build/mastering-host_artefacts/Release/mastering-host.exe` (check actual build output).

## Test plugin inspection
```powershell
$hostExe = ".\native\build\mastering-host_artefacts\Release\mastering-host.exe"
& $hostExe inspect --plugin "C:\Program Files\Common Files\VST3\FabFilter Pro-Q 4.vst3"
```

## Test rendering (never overwrite the original)
```powershell
& $hostExe render --plugin "C:\Program Files\Common Files\VST3\FabFilter Pro-Q 4.vst3" --input ".\test_input.wav" --output ".\test_output.wav" --state-out ".\proq_state.bin"
```

**Note:** The default plugin state may be transparent, so successful rendering need not change the sound. Inspect parameters first, select a safe parameter, and confirm its effect by listening and measuring. Parameter indices are plugin/version-specific. Some plugins may require message-loop servicing, GUI initialization, licensing, or different processing setup. Do not run batch tests until a single plugin is verified.

## Limitations / next tasks
- No GUI message pump while processing; some plugins may not function correctly.
- Single stereo plugin only; no chain, sidechain, oversampling configuration or realtime playback.
- The simple latency compensation assumes a fixed reported latency and does not handle dynamic latency changes.
- Reverb tails are capped at 10 seconds.
- No VST3 crash sandbox beyond the command-line process; launch via Python with timeout.
- 24-bit WAV output; no true-peak safety or mastering QC yet.
- Parameter listing may include unnamed, hidden, or unautomatable controls.


## v0.3 multi-parameter test (Windows PowerShell)

```powershell
cmake -S native -B native/build -G "Visual Studio 17 2022" -A x64
cmake --build native/build --config Release --target mastering-host
python scripts/make_test_tone.py
$hostExe = ".\native\build\mastering-host_artefacts\Release\mastering-host.exe"
$plugin = "C:\Program Files\Common Files\VST3\FabFilter\FabFilter Pro-Q 4.vst3"
& $hostExe render --plugin $plugin --input ".\test-tone.wav" --output ".\test-eq.wav" --set 0:1 --set 3:0.6 --state-out ".\proq-test.state"
python scripts/compare_wavs.py ".\test-tone.wav" ".\test-eq.wav"
```

Pro-Q 4 Band 1 defaults to 1000 Hz / Q 1.0, as observed in the user's parameter report.
--set 0:1 activates the band; --set 3:0.6 requests a gain increase.
Check the JSON parameter_changes[].text to see the **actual** dB value.
This is a proof-of-concept only; no loudness normalization or true-peak limiting.
The source WAV is never overwritten. Note: parameter indices are plugin-version-specific.
