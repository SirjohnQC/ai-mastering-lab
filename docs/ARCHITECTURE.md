# Architecture decisions

- Python orchestrator: project metadata, audio measurements, scoring, optimization, UI (later).
- JUCE C++ host: VST3 discovery, instantiation, processing, state serialization, audio export.
- Cubase 14 adapter: optional, separate, best for human editing and manual refinement.
- No requirement to call a generative model in the audio processing loop.
- Plugin capability registry built from verified plugin parameters, not inferred labels.
- All original audio files remain untouched. Process floating point; dither only when required on final fixed-point export.
- Reference profiles are descriptive targets, not forced EQ curves.
- Stem mode requires reconstruction and alignment tests before processing.
- Objective metrics cannot replace level-matched human listening.
- True-peak ceiling and LUFS are configurable; -14 LUFS is not a mandatory mastering target.

## Security and reliability

- Scanning bundles by filesystem is safe but does not load plugins.
- Plugin loading can crash a process: use isolation or a dedicated scanner helper.
- Third-party plugin licenses and offline rendering support must be tested locally.
- Save plugin states and processing chain versions to reproduce outputs.
