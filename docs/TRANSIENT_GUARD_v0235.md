# v0.23.5 — Dynamic Impact / Transient Guard

## What changed
- For every Gentle and Firm render in Compare, read-only diagnostics compare **time-aligned 100 ms PCM windows** with the same mix's Original WAV.
- Silent windows are ignored; loud and quiet source windows are classified using *original* RMS percentiles.
- The UI displays the median **relative loud-versus-quiet RMS change**. A negative value means the processed loud windows have been reduced more than quiet windows.
- When the loud-vs-quiet change is below **-5 dB**, a cautious *review by ear* warning appears and the Auto Studio compression advisor **cannot recommend** this version.
- If the loud-vs-quiet metric and overall level change are both near zero, UI flags the effect as subtle.
- Measurement is cached under local `settings/` using an updated diagnostics version so old reports are not reused.
- No new rendering pass, song uploads, network inference, or changes to JUCE Pro-C parameter selection. Existing song-aware renders and all nine clocks remain unchanged.

## Caveats
The short-window PCM measure is **not FabFilter's gain reduction meter**, a true transient preservation meter, a quality score or LUFS. Thresholds are conservative heuristics, not guarantees. Music can legitimately be very compressed, so all output still needs listening review. We intentionally **do not block manual ♥ approvals**.

## Windows acceptance checklist
1. Switch to `feature/v0.23.5-transient-guard`, start `python scripts/desktop.py`.
2. Enter Compare and let local cached renders/updated diagnostics finish.
3. Choose Gentle/Firm on a dynamic song and observe `Passages forts vs calmes` metric in dB. This should be absent for Original.
4. Switch between Balanced/Vocal Focus/Punchy while playing and verify UI follows the selected WAV.
5. If warning appears, verify advisor does not suggest the affected variant; it remains possible to audition and ♥ manually.
6. Reopen Compare and check diagnostics cache reuse without regenerating JUCE audio if sources are unchanged.
7. Execute `python -m unittest discover -s tests -p "test_transient_guard_v0235.py"`, and run existing `test_compare_v0232.py`, `test_compression_advisor_v0233.py`, `test_adaptive_pro_c3_v0234.py`.
8. No originals, stems or user audio belong in the public repository.

A more accurate true-peak/transient model can follow once this measurement is validated on the actual Windows engine.
