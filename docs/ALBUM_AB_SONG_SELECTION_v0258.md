# v0.25.8 — Choose exactly which album song opens A/B

## Bug
In Album Studio v0.25.7, selecting a song was not reliable: the visible card is embedded in QListWidget using setItemWidget, so clicking the card's QLabel content did not consistently update QListWidget's current item. The global A/B button could therefore open the **first/stale** song instead of the one the user intended.

## Fix
- Clicking the song title / body of a card explicitly selects it by its stable source path.
- The global A/B button now shows the selected title (e.g. **♫ A/B · Bloom**) and is enabled only for a measured QC-passed master.
- Every song with a QC-passed, Album-Intelligence-measured WAV gets its own **♫ A/B** button directly on the card. This button opens the dialog **for that exact song**, independently of the previously selected row.
- The A/B dialog title includes the song name, to make accidental mismatch obvious.
- When the track list is rebuilt after scanning, reordering or processing, the selected path is restored when possible.
- All drag-and-drop, master files, QC metadata, standalone reference WAV and audio rendering behavior remain unchanged.

## Expected behavior
1. Analyze the album after mastering songs (QC pass).
2. Click anywhere on **Bloom**'s card other than an action button or drag grip. The main A/B button should update to **♫ A/B · Bloom**.
3. Click **♫ A/B** directly on Bloom's card, or the main A/B button after selecting it. The dialog title must say **Album A/B · Bloom**, and A must load Bloom's master.
4. Close; choose **Kids in Love** and repeat. A must now load Kids in Love.
5. Reorder tracks using the working drag grip, reanalyze as needed, then repeat. No accidental first-song fallback.
6. For songs without completed QC/analysis, A/B isn't offered; the user must produce and analyze those tracks first.
7. Run `python -m unittest discover -s tests -p "test_album_ab_song_selection_v0258.py"` and previous album regression tests.

Tests are included but await confirmation on the user's Windows/PySide6 machine. No private song, stem, master, reference file or local settings were committed.
