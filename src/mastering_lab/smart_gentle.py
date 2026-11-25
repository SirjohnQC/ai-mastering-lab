"""Smart Gentle candidate selection on *rendered* local WAVs.

No interpolation, no guessed Pro-C parameters, no AI inference. The plugin
readback/clip checks happen in the caller. This module only judges measured PCM;
signal differences are NOT equivalent to the plugin's gain reduction.
"""
from __future__ import annotations

from pathlib import Path
import math

from .compression_diagnostics import compare_wav_content, wav_profile
from .transient_guard import compare_windows

# Both values are present in the read-only validated getText grid.
THRESHOLD_POINTS = (0.85, 0.70)
TARGET_LOUD_DELTA_DB = -0.75


def gentle_candidates(adaptive_values: dict) -> list[tuple[str, dict]]:
    """Conservative original threshold first, then one alternate calibrated point."""
    if not isinstance(adaptive_values, dict) or set(adaptive_values) != {
            'threshold', 'ratio', 'attack', 'release'}:
        raise ValueError('Invalid Gentle base values.')
    if (adaptive_values['threshold'] not in THRESHOLD_POINTS
            or adaptive_values['ratio'] != 0.30
            or adaptive_values['attack'] != 0.30
            or adaptive_values['release'] != 0.30):
        raise ValueError('Unvalidated Gentle values.')
    order = (adaptive_values['threshold'],) + tuple(
        p for p in THRESHOLD_POINTS if p != adaptive_values['threshold'])
    return [(f'gentle-{index+1}', dict(adaptive_values, threshold=point))
            for index, point in enumerate(order)]


def evaluate_gentle(original: Path, candidate: Path, *, frames: int) -> dict:
    """Compare complete music frames; returns a reviewable measured score."""
    original, candidate = Path(original), Path(candidate)
    baseline = wav_profile(original, bins=32)
    output = wav_profile(candidate, bins=32)
    delta = compare_wav_content(original, candidate, frames=frames)
    windows = compare_windows(original, candidate, frames=frames)
    result = {
        'rms_delta_db': delta['rms_delta_db'],
        'same_samples': delta['same_samples'],
        'sample_peak_dbfs': output['sample_peak_dbfs'],
        'crest_db': output['crest_db'],
        'window_analysis': windows,
        'status': 'rejected',
        'reason': 'No suitable measurable compression',
    }
    if windows.get('status') != 'measured':
        result['reason'] = 'Not enough active windows'
        return result
    if delta['same_samples']:
        result['reason'] = 'PCM identical to Original'
        return result
    if (output['sample_peak_dbfs'] is None or output['sample_peak_dbfs'] >= -0.2
            or output['crest_db'] is None or output['crest_db'] < 5
            or baseline['crest_db'] is None
            or baseline['crest_db'] - output['crest_db'] > 3.5):
        result['reason'] = 'Peak / dynamic safety guard'
        return result
    loud = windows['loud_rms_delta_db']
    relative = windows['loud_relative_to_quiet_db']
    if (loud < -3.0 or abs(relative) > 4.0
            or windows['overcompression_warning']):
        result['reason'] = 'Excessive local processing'
        return result
    # No requirement that compressors always lower the global RMS, and
    # no claim that loud-window dB change is internal plugin GR.
    if abs(loud) < 0.12 and abs(relative) < 0.12:
        result['reason'] = 'Insufficient audible-level PCM change'
        return result
    score = abs(loud - TARGET_LOUD_DELTA_DB) + max(0.0, abs(relative) - 2) * 0.5
    result.update(status='eligible', reason='Light measurable PCM processing',
                  score=round(score, 4))
    return result


def choose_gentle(evaluations: list[dict]) -> dict:
    """Only eligible render can win; otherwise preserve unprocessed Original."""
    valid = [e for e in evaluations if e.get('metrics', {}).get('status') == 'eligible'
             and e.get('path') and e.get('name')]
    if not valid:
        return {'status':'fallback_original', 'selected':'original',
                'reason':'No Gentle candidate met the conservative PCM checks.'}
    best = min(valid, key=lambda e: (e['metrics']['score'],
                                      THRESHOLD_POINTS.index(e['threshold'])))
    return {'status':'selected', 'selected':best['name'],
            'threshold_normalized':best['threshold'],
            'metrics':best['metrics'],
            'reason':'Closest measured loud-window change to gentle target; audition required.'}
