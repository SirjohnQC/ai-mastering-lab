# v0.25.2 — Smart Master Import & Reference Clarity

## Two distinct reference concepts

- **Reference Learning — Inspiration sonore**: your selected WAV/FLAC/MP3 inspirations yield a sampled spectral/crest profile stored in the ignored local `settings/reference_learning.json`. Selected mix evaluation and AI FX/EQ proposals can receive this profile as an optional weak preference. The plugin/mastering audio engine does NOT automatically learn, copy or match these songs, and Hermes is not fine-tuned.
- **Album Reference — Cohérence de l'album**: a **QC-passed master of your own album** is used by Album Intelligence as the anchor for comparing integrated loudness, actual QC true peak, and relative broad-spectrum differences. It has nothing to do with choosing a commercial/reference song in Reference Learning.

The Reference Learning dialog now explicitly explains what its profile does and does not do; the Album Reference selector is renamed to make the distinction clear.

## Recognize a previously mastered WAV

v0.25.1 treated *all* imported WAVs as `waiting`, even when they were already mastered in Auto Studio, with an adjacent `.qc.json` file. This prevented a legitimate master from being chosen as the album reference and encouraged unnecessary double mastering.

v0.25.2 adds a **read-only** recognition pass:
1. For each new stereo WAV imported with a matching sibling `.qc.json`, a background worker verifies the existing master automatically. Previously imported waiting WAVs can be checked using the new **Reconnaître les masters QC existants** button.
2. The QC sidecar must indicate `qc_pass`, contain the same absolute WAV path, and have complete stereo 24-bit PCM file metadata. A different file or stale metadata is rejected.
3. The worker independently **remeasures the actual WAV using local FFmpeg**. LUFS and TP must agree with the stored report within 0.15, and actual true peak must not exceed −1.0 dBTP. A missing FFmpeg, missing sidecar, modified file, unsupported format, or QC failure leaves the track `waiting` with an explanation.
4. A recognized track gets a local `album_source_signature`, so the existing album batch re-use logic knows it is an already mastered file and can avoid making another master. Album reference selection then becomes available.
5. The original WAV and its QC sidecar are **never modified** during recognition. There are no VST/FFmpeg render calls, uploads, or album-level automatic EQ.

The old v0.24.3 file "Voicemail From 2004" should be recognized when imported from its original location together with its `.qc.json` sidecar; **only if independent local verification succeeds**.

## Windows acceptance

1. Switch to `feature/v0.25.2-smart-master-import-references` and run `python scripts/desktop.py`.
2. Open **Album Mode**. If the existing song is `waiting`, click **Reconnaître les masters QC existants**. With its sibling `.qc.json` still present and FFmpeg available, it should become `qc_pass` and appear in **Référence d'album (master QC)** without running Auto Produce Album.
3. Import another *already mastered* QC-passed WAV through **Ajouter des WAV**. Verification should start automatically in the background.
4. Import an arbitrary unmastered WAV or one without a sibling `.qc.json`: it stays waiting; it must NOT be automatically master-certified.
5. Choose a recognized album master and run Album Intelligence + Match Advisor from v0.25.0/.1. Verify album reports still remain local.
6. Open **References**: confirm the modal identifies Reference Learning as *musical inspiration* rather than an album QC master reference.
7. Run `python -m unittest discover -s tests -p "test_smart_master_import_v0252.py"` and prior version tests.
8. Check `git status`: no `settings/`, `sound/`, `audio/`, songs, masters, or QC JSON should be pushed.

## Caveats

This only recognizes genuine **AI Mastering Lab master files** with an associated, valid `.qc.json`; it does not retroactively certify externally mastered WAVs or perform a forensic hash check on the source. The remeasurement is intended to detect stale reports, not to assess subjective audio quality.

Audio and personal settings are local; PR stays draft until Windows/Qt/FFmpeg testing. Album Studio's inherited dialogs still contain French labels when English is selected, a separate localization improvement.
