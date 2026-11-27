<p align="center">
  <img src="src/mastering_lab/assets/frankenstem-wordmark.svg" alt="FRANKENSTEM — AI Mastering Lab" width="800">
</p>

# FRANKENSTEM · AI Mastering Lab

A local Windows studio for stem mixing, comparing alternatives, technical mastering and album preparation. The current desktop application reports **v0.27.4**. Audio processing uses Python, FFmpeg and an optional native JUCE/VST3 host; local Ollama models provide optional advice.

## Start with the music

1. **Import** one song’s stems. Check the selected tracks and enter a song title.
2. **Produce** three premix alternatives: Balanced, Vocal Focus and Punchy.
3. **Compare** the mixes and available compression previews. Listen before choosing; the heart approves compression for mastering. Without an approved compression choice, the original premix is used.
4. **Master** the selected source, listen to the result and review QC/pre-release checks before collecting the WAV.

For multiple songs or an existing stereo WAV, open **Album Mode**. **References** manages local reference profiles. **Advanced / STEM+ Console** exposes individual stem controls. The separate **MASTERING / Stereo** workspace is the older reference-EQ candidate tool; final Auto Master is inside Auto Studio.

Original audio remains local. Premixes are not final masters, and passing technical checks does not replace listening.

## Run the desktop app

Use Python 3.10+ on Windows. From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[analysis,dev]" -r requirements-gui.txt sounddevice
python scripts/desktop.py
```

Install FFmpeg and make `ffmpeg`/`ffprobe` available on PATH for mastering and audio conversion. Build the native host and configure installed, licensed plugins for the VST3 features; see [native build instructions](native/README.md). Pro-Q 4/Pro-C 3 workflows require compatible installed plugins and, for calibrated compression previews, local calibration. Ollama is optional for advice; availability of each audio operation depends on its local tools.

This is a source checkout workflow. The desktop and package versions are both `0.27.4`. The startup loading card displays the FRANKENSTEM logo and version; the main workspace keeps a simple text heading.

## UI and workflow review

The [UI review and improvement proposal](docs/UI_FLOW_REVIEW.md) records findings, implemented improvements and the next recommended changes. This iteration adds a reusable vector logo, a clearer bilingual workflow, readable disabled actions, keyboard focus cues and scrolling for smaller displays.

Brand assets:

- [App icon](src/mastering_lab/assets/frankenstem-icon.svg)
- [Wordmark](src/mastering_lab/assets/frankenstem-wordmark.svg)
- [Brand usage](docs/BRAND.md)

## Validation

Focused UI regression checks (no user audio or plugin rendering):

```powershell
$env:PYTHONPATH = 'src'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest -q tests/test_studio_workflow.py tests/test_auto_studio_ui.py tests/test_import_layout.py tests/test_guided_lock.py tests/test_reimport_navigation.py
```

The full historical suite currently has collection conflicts from test modules replacing `sys.modules`, plus stale source/version assertions. See the review for the baseline and validation scope. End-to-end playback, device behavior and licensed VST rendering still require Windows listening tests.

## Project notes

- [Architecture](docs/ARCHITECTURE.md)
- [Live audio engine](docs/FRANKENSTEM_LIVE_AUDIO_ENGINE_v0270.md)
- [Album workflow](docs/ALBUM_INTELLIGENCE_v0250.md)
- [Compression diagnostic module (archived README)](docs/COMPRESSION_DIAGNOSTICS_v0232.md)

Audio, plugin binaries, renders, caches and personal settings are excluded from Git. The older README was specific to a v0.23.2 diagnostic patch; it is preserved as historical documentation rather than presented as installation instructions for the current app.
