# FRANKENSTEM identity

The mark combines three separate violet stem signals with a mint F-shaped output. It represents assembling a mix from independent tracks and remains readable as a small desktop icon.

- **Product:** FRANKENSTEM
- **Descriptor:** AI Mastering Lab
- **Mint / primary action:** `#73E2BF`
- **Violet / selection and focus:** `#AAA3FF`
- **Canvas:** `#11151F`
- **Surface:** `#171E2C`
- **Primary text:** `#F0F5FF`
- **Secondary text:** `#A8B6CB`

Use `src/mastering_lab/assets/frankenstem-icon.svg` for the app icon and compact header. Use `frankenstem-wordmark.svg` for repository and presentation headers. Both are editable SVG assets with no remote resources. The wordmark uses Segoe UI with Arial/sans-serif fallbacks; the icon is entirely vector geometry. Keep clear space of at least one signal-bar width around the mark. Preserve the dark tile when placing the icon on a light background.

The assets are bundled through setuptools package data and resolved relative to the Python module, so they do not depend on the current working directory. Disabled actions use a muted surface; reserve mint for available primary actions. Focus and selection must also have a visible border/state, not just a color change.
