# AI Mastering Lab v0.14.1 — Import List Layout Fix

UI-only patch on top of v0.14.0.

## Fix
- The selected-stem list moves to the previously blank area ABOVE the import form.
- The list grows to fill available vertical space and scrolls when there are more stems than fit.
- Import actions and Auto Produce remain below the list.
- Empty-state form retains its centered placement.
- Removing stems still only changes the selection; original WAVs are not deleted.

## Installation
Back up your v0.14.0 project. Copy `src/mastering_lab/auto_studio_ui.py` and `src/mastering_lab/version.py` from this archive into the same paths of your existing project. Do not replace the entire `src` folder or delete other project files. Then run `python scripts/desktop.py`.

## Verification
Five structural tests pass and Python compiles. PySide6 UI rendering must be validated on Windows.
