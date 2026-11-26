# v0.25.5 — Album drag and drop directly onto a song card

## User report
v0.25.4 allowed reordering only when the cursor landed on Qt's extremely narrow insertion bar **between** cards. Dropping **on** an existing song card felt broken.

## Fix
- The entire hovered album song card is now a valid drop target, with a visible violet outline/background.
- Start from the existing `⠿` grip and drop directly onto the card at the desired position. No tiny insertion bar.
- A drop moves the dragged song to the hovered song's **original position**, shifting the other tracks accordingly. It does **not** replace, overwrite, duplicate, or delete the target song.
- The move is applied to complete song records (QC reports, candidate paths, stems and master paths stay attached), saved in `settings/album_project.json`, and displayed using updated track numbers.
- A drop on itself or outside all album cards does nothing. Reordering stays disabled while production/QC scan/album analysis is running.
- Album reference WAV remains outside the reorderable list. Existing album analysis text is cleared after an order change to avoid mismatched numeric indices.

## Windows acceptance
1. Checkout `fix/v0.25.5-album-card-drop-target`, start `python scripts/desktop.py`, open Album Mode with three or more songs.
2. Grab song #3 using `⠿` and drop **anywhere on song #1's card**, not on the gap. Confirm the card highlights violet and #3 becomes #1.
3. Grab song #1 and drop it on song #3's card. Confirm it moves to that slot while no song disappears.
4. Drop onto the same card and outside any card; verify no unintended movement.
5. Close/reopen, check saved order, QC statuses and master paths.
6. Verify drag is disabled during processing.
7. Run `python -m unittest discover -s tests -p "test_album_drop_on_card_v0255.py"` and v0.25.4 album reorder tests.

No audio or private project data is published. This UI fix is in a draft PR stacked on v0.25.4 (#18) pending actual PySide6 Windows testing.
