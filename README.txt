AI Mastering Lab - Auto-folder discovery patch for v0.4

Copy scripts/reference_eq.py into your existing project's scripts/ folder (replace existing file).

Optional: copy tests/test_folder_discovery.py into tests/ for regression tests.

Put one reference WAV in sound/ref/ and one or more source WAV files in sound/source/.

From project root:
    python scripts/reference_eq.py

This analyzes all WAV files and writes individual JSON reports under sound/output/.
To process them through the Pro-Q 4 host:
    python scripts/reference_eq.py --render

Other useful options:
    python scripts/reference_eq.py --reference "sound/ref/my-master.wav"
    python scripts/reference_eq.py --source "sound/source/song.wav"
    python scripts/reference_eq.py --help

Only WAV is supported for now. Non-WAV audio is ignored in auto mode, not converted.
More than one WAV reference in ref/ requires --reference explicitly.
Sources remain untouched. Output is written to sound/output/.

NOTE: Reference EQ is not a finished master; use careful listening and verify peaks before release.
