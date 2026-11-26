# AI Mastering Lab v0.26.1 — Smart A/B Decisions + Creative Alternatives

## The user issue

When **Kids in Love** was already close to the selected external WAV reference (max broad-band difference ~2.4 dB), v0.26.0 rendered a scary `ValueError: No reliable, meaningful tonal difference to preview`. This was an expected *no-op*, not an audio processing failure. And users wanted to experiment artistically without claiming a false reference correction.

## Decision states in the A/B dialog

- **✓ Already close**: measured differences do not justify a reference-matching EQ. Reference Match's render button is disabled; A remains completely available to listen to.
- **⚠ Uncertain**: missing/invalid QC spectral metrics, extreme >18 dB relative energy differences, or an ineligible reference. The app refuses automatic reference matching rather than inventing a correction.
- **Tonal Match available**: the existing conservative reference-based EQ B may be generated.
- All three states are rendered as normal informational UI text. They are no longer exposed as raw Python exceptions.

## Creative Alternative mode

The A/B dialog now has an explicit mode selector:
- **Reference Match · Cohérence**: the original v0.26.0 bounded EQ proposal, offered only when a significant reliable broad-band difference is measured.
- **Creative · Warm**: subtle +0.65 dB near 350 Hz, −0.45 dB near 4.4 kHz.
- **Creative · Presence**: subtle −0.35 dB near 1.2 kHz, +0.75 dB near 4.4 kHz.
- **Creative · Air**: subtle +0.35 dB near 4.4 kHz, +0.55 dB near 11 kHz.

Creative is an *optional experiment*, not a necessary fix, not inferred from the reference and not a promise of better sound. Filters are applied with FFmpeg's equalizer and the same one-octave-or-so restraint as reference matching. The script only permits creative previews for QC-passed album songs that already have a completed Album Intelligence analysis.

## Production guarantees

- B is rendered to `sound/output/album_studio/ab_previews/` using an existing source WAV; never overwrites original A, its QC sidecar, stems or independent reference.
- After EQ, B is loudness-matched to **A** within ±0.25 LU, with compensation capped at ±1.5 dB. No loudness-bias shortcut.
- The complete B WAV is independently measured with FFmpeg. **True Peak must be ≤−1.0 dBTP** or the preview is rejected. No destructive limiting is inserted merely to force a match.
- Creative mode and style are in the cache fingerprint, preventing mixing up Warm, Presence, Air and Reference Match copies.
- Switching the mode clears the previous B in the player and returns to A if B was playing. Your ♥ still approves only the audition manifest for future export; it never silently re-exports a master.
- Audio and local preferences remain local. No new network model or training action.

## Windows acceptance checklist

1. Checkout `feature/v0.26.1-smart-ab-creative` and run `python scripts/desktop.py`.
2. In Album Mode, choose the standalone WAV, analyze album and click **♫ A/B** on **Kids in Love**.
3. Reference Match should show **✓ Déjà proche de la référence** when spectral deltas are all below the thresholds; it should not print `ValueError` or offer a needless EQ.
4. Switch the dropdown to **Creative · Warm** and click **Préparer B**. The app should render a separate B if measured peak and loudness allow it.
5. Switch A↔B while playing, compare by ear, and optionally try Presence and Air.
6. Confirm that switching styles resets the active B selection, requires a separate rendered preview and never replaces the original WAV.
7. Verify the cache JSON contains `mode:creative`, the selected `creative_style`, measured LUFS and verified True Peak; A remains untouched.
8. Run `python -m unittest discover -s tests -p "test_smart_ab_creative_v0261.py"` and earlier v0.26.0 tonal-match regression tests.

## Limitations / next steps

Current A/B switches decoded media sources in Qt Multimedia while preserving approximate timeline position; true gapless crossfading still requires a separate transport upgrade. The creative EQ variants are intentionally mild static choices, not an AI-generated mastering recommendation or Pro-Q 4 chain. There is no distribution-ready B export yet.

Tests are authored in the repo; full Windows/PySide6/FFmpeg integration remains to be validated by the user before merging this draft stacked PR on v0.26.0 (#23).
