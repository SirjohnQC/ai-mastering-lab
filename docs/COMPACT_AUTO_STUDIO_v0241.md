# AI Mastering Lab v0.24.1 — Compact Auto Studio

## Scope and intent

This is a **UI cleanup**, not a rewrite of the mixing, Pro-C 3, Hermes or mastering engine. The existing stem-based **AUTO PRODUCE** workflow remains the same: Importer → Produire → Comparer → Mastering. No unsupported promise of direct single-WAV or whole-album one-click mixing is made in this update.

## Changes

**Comparer — simple by default**
- Main view keeps three premixes, Original / Gentle / Firm, the shared waveform with pink markers, local Hermes/PCM recommendation, playback/level matching, explicit ♥ approval and Continue to Mastering.
- All low-level readouts (absolute WAV path, RMS/peak/crest, normalized VST controls, Smart Gentle trial details, threshold activity and marker timestamp buttons) are available under the collapsed **⚙ Diagnostics · Advanced** section. Pink markers remain visible and clickable in the waveform even while diagnostics are hidden.
- Adds a short review hint, e.g. `3 passages à écouter`; reduces repeated long-form diagnostic paragraphs in the main comparison flow.
- No changes to nine-player transport sync, cached WAVs, Pro-C parameter safety, or local Hermes model requests.

**Secondary options**
- Previously visible legacy analysis, mix-AI details, EQ feedback, preference controls and A/B EQ panel now live behind a collapsed **⚙ Options facultatives · Advanced** section after Continue to Mastering.
- Their existing callbacks and widgets are retained; nothing is deleted.
- The original header Advanced button still opens the existing Advanced area. These inline disclosures are intended for optional diagnosis without leaving Compare.

**Production**
- The existing `AUTO PRODUCE` button still calls `start_guided_production()` and the existing progress screen and cancellation. Compare still prepares local audio automatically when entered, and only explicit ♥ can authorize a processed preview as a mastering source.
- Original stems, WAVs, local `settings/`, private references and sessions stay on the user's PC. No audio was committed.

## Windows acceptance

1. Switch to `feature/v0.24.1-one-click-auto-produce-ui` and start `python scripts/desktop.py`.
2. Open a previously produced session → Comparer. Confirm the top of the view shows mix/compression choices and shared waveform without the long diagnostic labels.
3. Play, switch Original/Gentle/Firm and Balanced/Vocal Focus/Punchy mid-song: no restart. Click pink waveform markers to seek.
4. Open **Diagnostics · Advanced**: verify WAV path, peak/RMS/crest, Smart Gentle, threshold activity and marker timestamp buttons.
5. Close/reopen that section while audio plays; playback should continue.
6. Open **Options facultatives · Advanced** and check existing EQ A/B, mix report and user preference controls remain accessible.
7. Click ♥ to approve a compression and proceed to Mastering; without ♥, Original must remain the mastering source. The Smart Gentle fallback must still block ♥ Gentle.
8. Import new stems and use the existing **AUTO PRODUCE** button: verify progress → Compare. No source files should change.
9. Run `python -m unittest discover -s tests -p "test_compact_auto_studio_v0241.py"`, then earlier version tests.

## Validation caveat

Tests are included in the public repository, but **this PR has not been verified on Windows with PySide6, FabFilter, JUCE or Ollama**. It remains a draft PR stacked on #9. Merge only after checking the local UI and all earlier dependent PRs. No automatic output certification or subjective quality guarantee is implied.
