# Analyze, correct, rate and refine — v0.28.0

The guided Compare screen now exposes the feedback loop instead of hiding it in optional tools.

## Single-song flow

1. Import stems and run Auto Produce. The existing pipeline analyzes stems, proposes FX, renders approved processing and produces three premixes.
2. Compare Balanced, Vocal Focus and Punchy. In the ratings panel, selecting a version switches the common player to its **Original** premix, before compression. Use the player to listen, then score each mix from 1 (dislike) to 5 (love).
3. Save ratings and use the favorite. The highest score wins; ties require selecting a favorite among the highest-rated versions. Saving again updates the same session rather than adding another vote.
4. Choose **Use my ratings to create the next pass**. This saves the current ratings, sends recent preference examples alongside measured audio features to local Hermes, and shows its proposed gain changes before rendering new files. If Hermes fails, the fixed fallback explicitly reports that it did not use preferences.
5. Listen and rate again. Generations are numbered correctly beyond generation 2 and retain their parent reports. Every pass starts from the saved source configuration and prepared inputs, with bounded gain offsets; offsets are not compounded indefinitely.

## Targeted EQ correction

The visible **Analyze and propose an EQ fix** action opens the existing correction workflow: measured spectral features → local AI proposal → approve a separate Pro-Q 4 render → Before/After listening.

The Before/After preference buttons record whether that specific EQ move helped. Future EQ proposals consume this separate memory. A vote for Before does not imply that the inverse EQ should be applied.

**Use this EQ version for mastering** explicitly selects the rendered correction as the next mastering source. It does not launch Auto Master itself. This path uses the EQ-treated original premix, without Pro-C 3 compression; it does not pretend to combine two independently rendered treatments. Changing the mix or generation clears the EQ approval. A missing approved file is reported instead of silently substituting a different source.

## What the analysis actually does

- Mix analysis measures audio and sampled spectral energy directly. Spectrogram image review is an optional local vision-model observation step, not a generic artifact-removal engine.
- The vocal whistle scanner detects persistent narrow peaks for review. The album automatic cleanup path separately targets conservative, short high-frequency noise bursts with a bounded De-Sizzle treatment. These are specific detectors, not proof that any unusual frequency is unwanted.
- Ratings now reach both candidate recommendations and generation proposals. EQ Before/After feedback reaches future EQ proposals. The application stores local examples; it does not retrain neural-network weights.
- Generation proposals adjust stem-family gains within ±1 dB and preserve Balanced. They cannot invent arbitrary filters or plugin changes. EQ trials use the existing validated EQ renderer. No new artifact-removal DSP was introduced in this UI/learning update.
- Mix ratings concern the uncompressed premixes, not compression choices or EQ trials. All three scores are explicit; the app does not infer a vote from an AI recommendation or a click on a mix.

## Regression checks

Tests cover score validation, session replacement, private path/title exclusion from preference summaries, ratings reaching the generator, honest offline fallback, UI reset, third-generation rendering, cached-preview handoff and explicit corrected-WAV selection without automatic mastering. Existing gain limits, source preservation and preference-selection safety checks remain covered.

Actual plugin rendering and listening require the installed Windows audio environment. Automated tests use synthetic WAVs and controlled model responses; they do not establish perceptual improvement.
