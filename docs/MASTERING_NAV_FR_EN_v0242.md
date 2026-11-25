# v0.24.2 — Mastering navigation fix + FR/EN guided UI

## Reported regression
In v0.24.1, **Continuer vers Mastering** did not navigate reliably for a user with a complete 9-WAV comparison session. The existing handoff depended on the legacy `MixCompareDialog` for obtaining the premix source, even though the common comparison player owns the active source mapping.

## Fixes

- The handoff now **prefers the valid premix in UnifiedComparison._sources**, using the legacy dialog only as fallback.
- It still honors **explicit ♥ approval** for compression. Without a heart, Mastering receives the unprocessed premix; if Smart Gentle fell back to Original, it cannot be approved as Gentle.
- Any exception while preparing Mastering is displayed via a message box with the exception type and text instead of looking like a dead click.
- The button still goes to existing Mastering page `_go(3)` and **does not automatically start rendering**.
- Failures remain visible for missing source files or a running Pro-C 3 worker.

## Language selector

- A new **Français / English** selector in the main Auto Studio header stores preference locally with `QSettings`.
- Primary Importer, Produire, Comparer, Mastering and common comparison labels switch without recreating audio players.
- Main Mastering labels, song-title input, approval controls and key navigation messages are translated.
- Internal identifiers and Hermes prompt formats remain unchanged. Local language preference does not require network access.
- **Scope caveat:** older Advanced tools, some legacy dialogs and dynamic Hermes explanations are *not yet fully localized*. This is a bilingual foundation, not a claim that the entire 2,000+ line legacy application has been translated.

## Windows verification

1. `git fetch origin`, switch to `fix/v0.24.2-mastering-navigation-bilingual-ui`, launch `python scripts/desktop.py`.
2. Load the existing nine-combination session and select Balanced + Gentle. Press ♥ Gentle, then **Continuer vers Mastering**. Verify it opens the Mastering page with the selected approved Gentle copy **without starting AUTO MASTER**.
3. Return, switch to Original without clicking a new heart. Confirm the existing approval behavior; for a clean session without ♥, Original must be used.
4. Switch mixes and repeat with Vocal Focus and Punchy; verify paths are correctly resolved from UnifiedComparison.
5. Use Français / English selector while playback is active; verify controls switch and playback continues; restart and verify language persists.
6. Open **Diagnostics · Advanced** and **Options facultatives · Advanced**, verify audio and full readouts are intact.
7. Run `python -m unittest discover -s tests -p "test_mastering_language_v0242.py"`, plus previous UI/Qt tests.
8. If navigating still fails, copy the new **Mastering error dialog**; it now reports the specific exception.

## Privacy

Only source code, test and documentation changes in this PR. `audio/` and personal stem, song, mastered output, session WAV and runtime `settings/` trees remain local and must not be pushed.

Draft PR is stacked on v0.24.1 (#10). Windows Qt/JUCE acceptance remains required before merging.
