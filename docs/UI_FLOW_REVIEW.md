# FRANKENSTEM UI and workflow review

Reviewed 2026-11-27 against `6d6416c` (desktop v0.27.3), the head of `feature/v0.27.3-vocal-whistle` at review time. This review covers the Python/Qt desktop UI, source, repository structure and synthetic UI tests. It is not an audio-quality certification or a licensed-plugin listening test.

## Repository findings

| Finding | Consequence | Recommendation |
| --- | --- | --- |
| The checkout was detached at the current feature head; `main` was still `94df267`, 232 commits behind this checkout. | Visitors and fresh clones do not see the developed app by default. | Review and integrate the accumulated feature work separately; publish this UI change against the current feature branch so its diff stays reviewable. |
| README described only a v0.23.2 diagnostic patch. | Setup and product capabilities looked incomplete. | Replaced with current workflow and launch instructions; preserved the diagnostic README in docs. |
| Desktop version is 0.27.3; package metadata says 0.5.0. | Releases and installed-package identity disagree. | Adopt one version source in a dedicated packaging change. |
| Historical tests install global mock modules and assert old version literals. | The complete suite cannot collect reliably; old checks produce misleading failures. | Isolate mocks with fixtures/subprocesses, replace version literals with behavioral assertions, then establish a reliable CI baseline. |

## Software and flow findings

| Priority | Observed issue | Change in this iteration |
| --- | --- | --- |
| High | Hidden Advanced console and lazy-loaded Album page required over 1,000 pixels of window height. | Scroll the console, Album and Master pages; verified main window at 1140 × 760, including after opening Album. |
| High | Compare navigation could leave the production screen without using the existing busy guard. | Reuse `_can_change_music()` before navigating to Compare; test rejected navigation and active-step state. |
| Medium | Import text promised Album Mode in a future release despite an existing Album button. | Explain the actual single-song and album/stereo entry points in FR/EN. |
| Medium | Disabled Auto Produce looked enabled because its local primary style overrode the disabled theme. | Explicit disabled styling and guidance explaining when production becomes available. |
| Medium | Brand, language and utilities competed in a crowded header. | Separate identity/language from Album, References and Advanced actions. |
| Medium | Stages lacked persistent next-action guidance. | Number the four steps, expose selected state to accessibility, add translated tooltips and contextual guidance, including Album Mode. |
| Low | Unrelated stereo-source requirements appeared in the status bar on Auto Studio. | Show the active workspace name when leaving the stereo tool. |

## Proposed next iteration

The target flow is **Choose session → Import → Produce → Compare and approve → Master → Check and export**.

1. **Choose a session type once.** Offer Single song, Stereo WAV and Album at the start. Preserve the current Album implementation behind these entry points; do not build duplicate import pipelines.
2. **Make one action primary at each stage.** Import tracks, produce alternatives, approve a choice, create a master, then export. Move advanced stereo EQ and per-stem tools behind explicit editing actions once navigation tests cover their handoffs.
3. **Persist session context.** Show song name, selected mix/compression and render status above the transport. Keep “previewed,” “approved” and “exported” distinct. A recommendation must never appear as an approval.
4. **Unify listening.** One transport, visible active audio version, loudness-match state and waveform for the actual selected WAV. Preserve the current synchronized playback and approval semantics during any visual refactor.
5. **Separate delivery from rendering.** Present QC evidence, output path and export controls as an explicit final stage. Keep technical checks and subjective listening separate; do not show “release ready” solely because a render completed.
6. **Finish localization and component cleanup.** The guided flow is bilingual, but the desktop menus and parts of the advanced tools still mix languages. Extract shared button/theme components incrementally instead of further expanding the large UI modules.

## Validation and limits

- Before changes, `pytest -q` stopped with **8 collection errors**. `tests/test_album_candidates.py` installs module stubs globally; other tests later import missing functions from those stubs. Additional global module replacements exist in vision tests.
- A clean archive of the original commit reproduced **6 failures / 33 passes** across the same eight legacy UI test files used for comparison. These failures concern two old navigation-source assumptions, old version literals, a missing test fixture path and an old calibration-dialog assumption.
- The focused acceptance set passes **26 tests**, including six new native Qt tests. It covers empty state, FR/EN switching, synthetic WAV import without source changes, blocked navigation, passive Master navigation, Album return navigation, SVG rendering and laptop geometry.
- Another **17 album regressions pass** across project persistence, reference-picker layout and whole-card drag targets.
- Built the wheel with isolated build dependencies and inspected its ZIP entries: both SVG assets are included. This does not validate the historical package version or make the native executable part of the wheel.
- UI screenshots were rendered with actual Qt widgets and Windows fonts in an isolated temporary project. User sessions were not restored; no user audio was opened or uploaded.
- No DSP, mastering targets, approval logic or plugin parameters were changed. Actual audio-device playback, production cancellation during a plugin render, and listening comparisons remain manual acceptance checks.

Run commands are in the root README. New UI tests exercise behavior; the obsolete historical tests remain visible rather than being silently removed.
