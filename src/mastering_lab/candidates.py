"""Three conservative, deterministic EQ candidate profiles and objective QC.

These are *not* AI quality scores. Human level-matched audition is still required.
"""
from __future__ import annotations
from dataclasses import asdict
import math
from pathlib import Path
from .reference import Analysis, CENTERS, analyze, suggest

# Broad and subtle creative tilts in decibels at each octave-band center.
# These are aesthetic starting points, NOT psychoacoustic truth.
TILTS: dict[str, tuple[float, ...]] = {
    'balanced': (0., 0., 0., 0., 0., 0., 0.),
    'warm':     (+0.35, +0.35, +0.15, 0., -0.10, -0.20, -0.30),
    'punchy':   (+0.20, +0.15, -0.20, -0.15, +0.25, +0.25, +0.10),
}

def plan_candidates(source: Analysis, reference: Analysis, *, strength: float = .55,
                    max_gain_db: float = 2.) -> dict[str, list[dict]]:
    """Return per-profile EQ plans with bounded total gain, based on measured reference."""
    base = suggest(source, reference, strength=strength, max_gain_db=max_gain_db)
    results = {}
    for profile, tilt in TILTS.items():
        rows = []
        for eq, bias in zip(base, tilt):
            value = max(-max_gain_db, min(max_gain_db, eq['recommended_gain_db'] + bias))
            rows.append({**eq, 'recommended_gain_db': round(value, 2),
                         'profile_tilt_db': round(bias, 2)})
        results[profile] = rows
    return results


def shape_distance(a: Analysis, b: Analysis) -> float:
    """Mean absolute spectral shape difference (dB, not a perceptual quality score)."""
    if len(a.spectral_shape_db) != len(b.spectral_shape_db):
        raise ValueError('Incompatible band shapes')
    return round(sum(abs(x-y) for x,y in zip(a.spectral_shape_db, b.spectral_shape_db)) /
                 len(a.spectral_shape_db), 3)


def measure_candidate(path: Path, original: Analysis, reference: Analysis) -> dict:
    rendered = analyze(path)
    original_dist = shape_distance(original, reference)
    result_dist = shape_distance(rendered, reference)
    original_rms = original.rms_dbfs
    delta_rms = round(rendered.rms_dbfs - original_rms, 3)
    # Peak is sample peak, NOT true peak. Dedicated TP measurement comes later.
    warnings = []
    if rendered.peak_dbfs > -1.0:
        warnings.append('Sample peak above -1 dBFS: review before limiting/export')
    if abs(delta_rms) > 1.5:
        warnings.append('Loudness changed noticeably: level-match for A/B listening')
    if abs(rendered.duration_seconds - original.duration_seconds) > .02:
        warnings.append('Audio duration differs from source')
    if result_dist > original_dist + .05:
        warnings.append('EQ candidate is further from reference tonal shape')
    return {
        'analysis': asdict(rendered),
        'spectral_distance_to_reference_db': result_dist,
        'source_spectral_distance_to_reference_db': original_dist,
        'spectral_distance_change_db': round(result_dist-original_dist, 3),
        'rms_change_db': delta_rms,
        'warnings': warnings,
        'interpretation': 'Spectral-distance improvement is NOT a mastering-quality score; audition at matched loudness.'
    }
