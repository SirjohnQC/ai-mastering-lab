# v0.25.1 — Album Match Advisor

## Aim
Turn the existing **Album Intelligence v0.25.0** reference audit into useful **non-destructive listening suggestions**. This is intentionally NOT an automated album EQ or a second mastering pass.

## How it works
1. Open Album Mode. Produce/import masters that have passed technical QC, and choose a reference master.
2. Press **Analyser la cohérence**. v0.25.0 reads local approved masters and measures integrated LUFS from stored QC, true peak from stored QC, and sampled relative FFT energy in five broad bands.
3. v0.25.1 builds one conservative review card for each song. It identifies whether the song is relatively quieter/louder (for a LUFS difference >1.5), whether one broad spectral band has more/less *relative* energy (>4 dB), and whether true peak needs review.
4. The original per-song measurement line remains visible; a new indented recommendation is appended underneath each song. The recommendation uses French or English according to Auto Studio's currently stored language preference.
5. A companion JSON file is saved **locally** as `sound/output/album_studio/album_match_advice.json` beside `album_consistency.json`. Both are ignored private runtime artifacts.

## Safety and interpretation
- LUFS delta is a measured *difference*, NOT a proposed fader adjustment in dB. A quiet ballad and an intense punk chorus do not necessarily need identical loudness.
- Band differences represent **relative energy shares** in sampled FFT windows, not guaranteed tonal imbalance. The advisor suggests *listening* in the most different broad region, **never an exact Pro-Q 4 gain/curve**.
- Extreme >36 dB band gaps are marked **unreliable** to avoid false EQ advice on sparse/silent frequency regions.
- Missing/unfinished QC masters cannot receive adjustment suggestions. The reference itself is never treated as a candidate for automatic changes.
- No Hermès prompt or VST parameter changes are part of this release. No output WAVs are modified, rendered, transmitted or re-normalized by the advisor.
- French/English **suggestion messages** are localized; older Album Mode UI text is still partly French and will need a separate cleanup.

## Windows acceptance
1. Switch to `feature/v0.25.1-album-match-advisor` and launch `python scripts/desktop.py`.
2. Open Album Mode. Prepare two or more QC-pass masters and choose a representative reference.
3. Click **Analyser la cohérence**. Confirm per-track measurement summaries and a new indented `↳` suggestion.
4. Try a loud acoustic track vs an energetic reference: the text should ask you to compare by ear, not insist on a volume fix.
5. Switch the language in Auto Studio, return to Album Mode and reanalyze: suggestion text should match the chosen language.
6. Review `sound/output/album_studio/album_match_advice.json`, ensuring it contains only analysis/review metadata, no audio.
7. Verify neither original stems nor masters have changed. No new rendering required for this update.
8. Run `python -m unittest discover -s tests -p "test_album_match_advisor_v0251.py"`, then v0.25.0 album tests.

## Future
A separate explicit **approve preview** phase can eventually render controlled album-level gain/EQ *alternatives* in local cache, audition A/B without replacing masters, and allow user approval and strict QC before export. v0.25.1 does not claim that capability.

This stacked PR depends on v0.25.0 (#14). Do not merge to main without Windows/PySide6 acceptance.
