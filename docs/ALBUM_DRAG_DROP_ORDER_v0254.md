# AI Mastering Lab v0.25.4 — Album track ordering by drag and drop

## What changed

- Album Studio's old **↑ / ↓ move buttons** are replaced with a visible **⠿ drag grip** beside each song.
- Hold and drag that grip to the intended position. The new order is persisted immediately in local `settings/album_project.json`, so closing and reopening Album Studio preserves it.
- The whole track object moves as one unit: source file, stem folder, chosen premix, QC state, error reports and final mastered WAV remain attached to the correct song.
- The new position is reflected in the track number, batch processing order and album report.
- The independently selected external reference WAV is *not* in the reorderable song list; reordering cannot touch it.
- Reordering is disabled while album production, import QC verification or Album Intelligence analysis is running. The existing remove button remains available when idle.
- Qt internal-move drag/drop is handled through a dedicated grip, including a fallback notification after a completed drop when Qt uses internal model remove/insert instead of rowsMoved.

## Notes on behavior

Reordering existing songs does not rerender or change their masters. An old album consistency report is cleared because its original list indices no longer match the rearranged tracklist; the user can rerun that read-only analysis. Reference selection remains tied to the source path rather than a list index.

No source files, exported WAV, local caches or settings are committed to the public repository.

## Windows acceptance

1. Fetch `feature/v0.25.4-album-drag-drop-order` and start `python scripts/desktop.py`.
2. Open Album Mode with at least three songs and drag the **⠿** grip from song 3 to the top. Confirm displayed numbers and titles update.
3. Close and reopen Album Mode; order must persist.
4. Check that each moved song still shows its original QC status and points to its own master WAV.
5. Select a standalone reference WAV before dragging; verify it does not appear in the list and is unchanged afterward.
6. Use Auto Produce Album: processing and summary must respect the saved song order.
7. While processing is active, verify drag/drop is disabled.
8. Run `python -m unittest discover -s tests -p "test_album_drag_drop_v0254.py"` and previous album tests.

## Status

Draft feature stacked on v0.25.3 (#17). Tests are authored in the repository but have not yet been executed on the user's Windows/PySide6 installation; approve only after real drag/drop and persistence acceptance.
