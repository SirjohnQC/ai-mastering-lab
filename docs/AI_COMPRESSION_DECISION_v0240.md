# v0.24.0 — AI Compression Decision (local Hermes3 advisor)

## Goal

After v0.23.9's real, measured Smart Gentle candidate selection, allow **the already configured local Ollama Hermes3:8b** model to recommend Original / Gentle / Firm for each of the three mixes and three audience intents, in the existing unified Compare screen.

## What changes

- A single asynchronous worker request to **127.0.0.1:11434/api/chat** asks for **9 selections** (3 mixes × Naturel / Équilibré / Énergique). No remote API.
- The request contains **only scalar PCM summaries**: sample peak, RMS, crest factor and relative loud-vs-quiet window change for **already allowed variants**. It never sends WAV bytes, song filenames, full local paths, plugin state, personal preferences, voice or stems.
- Deterministic Python safety checks run BEFORE the model receives a choice and AGAIN before displaying a cached choice in the UI. The allowed set always includes Original; it excludes overcompressed/clipped/identical WAVs and Smart Gentle's Original fallback.
- Hermes must return strict JSON with exactly nine keys; each recommendation must be whitelisted and carry a short French reason. Bad JSON, invalid data, untrusted recommendations, Ollama offline or timeout -> a fully labeled **PCM fallback**.
- Requests run in the existing PrepareNineWorker (not on the Qt UI thread). Local AI result is cached by source fingerprint in ignored `settings/pro_c3_unified_ai_compression.json`; reruns on changed inputs. **The pre-existing WAV render cache is NOT invalidated** (still schema 3).
- Existing mix and compression selectors, one shared waveform and player, and three user intents remain. Advisor text changes from `Conseiller PCM` to `Hermes local` only upon a validated local response; no new mandatory button.
- Hermes NEVER controls parameters in Pro-C 3 in this phase, modifies source audio, approves a version for Mastering, or bypasses explicit ♥.
- No track audio is uploaded to GitHub.

## Known limits

Hermes has no audio listening input here and does **not** measure musical quality, internal FabFilter gain reduction, LUFS or true peak. A PCM-based choice can be plausible yet sound worse; critical listening always decides. Local model output is one opinion among already-safe options, not a guarantee.

If Ollama is unavailable, the worker may take up to 12 seconds to try once (including cached-audio sessions); the deterministic PCM advisor then remains operational. A successful AI result is local-session-cached; invalid results cannot override safeguards.

## Windows validation checklist

1. Switch to `feature/v0.24.0-ai-compression-decision`. Ensure Hermes is installed locally: `ollama list`; `ollama serve` must already be running (if it is not, start it in a separate terminal).
2. Start `python scripts/desktop.py`, load a song and enter Comparer. Existing v0.23.9 WAVs should be reused from cache.
3. Once all analyses complete, the compare text should say **Hermes local** if the JSON response validated, otherwise **Conseiller PCM** with explicit fallback.
4. Change Naturel / Équilibré / Énergique and mix: each of nine combinations gets a corresponding recommendation without making more calls.
5. Check `Écouter la suggestion`: it should switch the active variant while keeping current position, without clicking ♥.
6. With Ollama stopped and with a deliberately invalid local response, confirm that the panel remains usable with PCM recommendations (there may be a 12 s timeout).
7. Verify Smart Gentle fallback still prevents ♥ Gentle when no candidate passed.
8. Confirm neither processing audio nor any private `settings/` data was committed. Run `python -m unittest discover -s tests -p "test_ai_compression_decision_v0240.py"` along with previous version tests.

### Next roadmap

- **v0.24.1 — One-Click Auto Produce**: simplify the main flow and put detailed diagnostics under Advanced, while preserving explicit confirmation for mastering.
- **v0.25.0 — Album Intelligence**: consistent tonal balance, dynamics and exports across songs using a reference mix.

Do not merge this draft into `main` before verifying Python/Qt/Ollama behavior on the actual Windows PC. Previous stacked PRs must be integrated in dependency order.
