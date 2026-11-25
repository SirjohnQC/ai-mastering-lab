"""Paired short-time diagnostics on already-rendered audio.

Measures synchronized stereo WAVs; NEVER claims to read VST gain reduction.
Time windows are 100 ms, chosen for robust loud/quiet and transient comparisons.
All calculations are read-only, streaming and limited to source music frames.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

WINDOW_MS = 100
EPS = 1e-12


def _db_ratio(numerator, denominator):
    return 20.0 * math.log10(max(float(numerator), EPS) / max(float(denominator), EPS))


def compare_windows(original_path, processed_path, *, frames=None):
    """Compare local dynamic behavior, robust to quiet and silent passages.

    Uses only synchronized windows with original RMS above -45 dBFS.
    If a JUCE render includes a short tail, caller supplies original frames.
    The median changes are not plugin gain reduction.
    """
    original_path, processed_path = Path(original_path), Path(processed_path)
    with sf.SoundFile(str(original_path)) as src, sf.SoundFile(str(processed_path)) as dst:
        if (src.samplerate != dst.samplerate or src.channels != 2 or
                dst.channels != 2 or src.samplerate != 48000):
            raise ValueError('Window comparison needs matched stereo 48 kHz WAVs')
        usable = src.frames if frames is None else int(frames)
        if usable <= 0 or usable > src.frames or usable > dst.frames:
            raise ValueError('Invalid synchronized music frame count')
        window = src.samplerate * WINDOW_MS // 1000
        records = []
        remaining = usable
        window_index = 0
        while remaining >= window:
            a = src.read(window, dtype='float32', always_2d=True)
            b = dst.read(window, dtype='float32', always_2d=True)
            if len(a) != window or len(b) != window or not (
                    np.isfinite(a).all() and np.isfinite(b).all()):
                raise ValueError('Invalid PCM samples or short read')
            rms_a = float(np.sqrt(np.mean(a.astype('float64') ** 2)))
            if rms_a > 10**(-45/20):
                rms_b = float(np.sqrt(np.mean(b.astype('float64') ** 2)))
                peak_a = float(np.max(np.abs(a)))
                peak_b = float(np.max(np.abs(b)))
                records.append((rms_a, _db_ratio(rms_b,rms_a),
                                _db_ratio(peak_b,peak_a), window_index * WINDOW_MS))
            remaining -= window
            window_index += 1
    if len(records) < 3:
        return {'status':'insufficient_active_audio','active_windows':len(records)}
    array = np.asarray(records, dtype=np.float64)
    # Level classes depend only on SOURCE RMS (never output RMS).
    loud_cut = float(np.percentile(array[:,0],75))
    quiet_cut = float(np.percentile(array[:,0],25))
    loud = array[array[:,0]>=loud_cut]
    quiet = array[array[:,0]<=quiet_cut]
    loud_rms_delta = float(np.median(loud[:,1]))
    quiet_rms_delta = float(np.median(quiet[:,1]))
    relative = loud_rms_delta - quiet_rms_delta
    # These are review suggestions, not detected audible artefacts.
    # Rank active, above-median SOURCE windows by processed-vs-Original
    # impact; keep distinct passages >=4 s apart and start 400 ms early.
    candidates = []
    median_source_level = float(np.median(array[:, 0]))
    for src_rms, rms_delta, peak_delta, ms in array:
        if src_rms < median_source_level:
            continue
        impact = abs(rms_delta - quiet_rms_delta) + 0.25 * abs(peak_delta)
        if impact < 0.30:
            continue
        candidates.append((float(impact), int(ms), float(rms_delta)))
    selected = []
    for impact, ms, rms_delta in sorted(candidates, key=lambda row: (-row[0], row[1])):
        if all(abs(ms - prior['source_ms']) >= 4000 for prior in selected):
            selected.append({
                'source_ms': ms,
                'seek_ms': max(0, ms - 400),
                'impact_score': round(impact, 3),
                'rms_delta_db': round(rms_delta, 3),
            })
            if len(selected) >= 3:
                break
    selected.sort(key=lambda row: row['source_ms'])
    # Relative high-level change is a *proxy*. It may be influenced by
    # makeup gain, EQ or signal shifts and is NOT VST gain reduction.
    return {
        'status':'measured','window_ms':WINDOW_MS,'active_windows':len(records),
        'loud_rms_delta_db':round(loud_rms_delta,3),
        'quiet_rms_delta_db':round(quiet_rms_delta,3),
        'loud_relative_to_quiet_db':round(relative,3),
        'loud_peak_delta_db':round(float(np.median(loud[:,2])),3),
        'overcompression_warning': bool(relative < -5.0),
        'review_markers': selected,
        'effect_nearly_inaudible_warning': bool(abs(relative)<0.15 and abs(loud_rms_delta)<0.15),
        'note':'Short-window PCM proxy, NOT FabFilter Pro-C 3 gain reduction. Markers are suggested review positions, not verified defects.',
    }
