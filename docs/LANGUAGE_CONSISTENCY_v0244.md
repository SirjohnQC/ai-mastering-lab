# Auto Studio v0.24.4 — Consistent FR/EN guided experience

## What this update fixes

The `Français / English` selector introduced in v0.24.2 changed many static labels, but several *dynamic* text updates could silently revert to French when a session loaded, an AI recommendation arrived, a master completed, or the user navigated.

v0.24.4 continues localization **without rewriting the audio engine**:
- Import and Produce page headings, safe-originals notice, loaded stems count, cancellation and preparation text follow the language preference.
- The bottom Mastering QC caveat and common dynamic status/error text now follow that preference.
- Compare statuses generated after cached WAV preparation, local Hermes/PCM recommendations, approval notices, review marker summaries and playback loading prompts are language-aware.
- When English is selected, untranslatable **free-form Hermes/PCM explanations** display a short, honestly generic English evidence statement rather than accidentally emitting the original French. The original French explanation is still available in French mode. This avoids pretending to machine-translate arbitrary AI output accurately.
- Switching languages updates displayed Compare content from in-memory measurements **without changing source WAVs, replay clocks or approval state**.
- The dictionaries live in `ui_language.py`; keys are shared between French and English.

## Scope and limitations

This update is specifically the **guided Auto Studio workflow**, not full localization of every historic Advanced, STEM+ Console, reference dialog or third-party VST plugin. The expanded Advanced PCM diagnostics may still contain French text; translating their complete explanations requires a separate pass, with actual evidence translations and no misleading audio claims. Existing JSON logs, metadata and reports retain their original data. New code does **not** send anything to a cloud translation service.

## Windows acceptance checklist

1. Switch to `feature/v0.24.4-language-consistency` and start `python scripts/desktop.py`.
2. In **English**, navigate Import, Produce, Compare, and Mastering. Look especially at the bottom Mastering caption, the audio preparation status and the approval text after clicking ♥.
3. Let local Hermes finish; the choice should be displayed in English mode, while dynamic free-form evidence is summarized conservatively.
4. Switch from English to Français and back while a cached song plays. Audio position, markers, ♥ approval and candidate eligibility must remain unchanged.
5. Open diagnostics: expect technical measurement labels to remain available. Some verbose Advanced diagnostics are not yet fully localized.
6. Run `python -m unittest discover -s tests -p "test_ui_language_consistency_v0244.py"`; existing tests for mastering safety and v0.24.3 should still pass.
7. No private WAVs, stems, masters, `audio/`, `sound/`, or `settings/` are committed. Source files stay on the user's machine.

## Follow-up

Once the above guided-flow checks pass, **v0.25.0 — Album Intelligence** can build an album reference profile and compare individual masters for consistency without modifying them blindly. Finish translation of the remaining old Advanced tools as a separate maintenance pass.

This draft PR is stacked on v0.24.3 and is not merged into `main`.
