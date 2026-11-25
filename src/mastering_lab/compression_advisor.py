"""Conservative music-aware recommendation among already rendered Pro-C 3 variants.

This is an explainable PCM heuristic, NOT Hermes inference, NOT VST gain
reduction telemetry and NOT an automatic mastering approval. No audio written.
"""
from __future__ import annotations

import math

MIXES = ('balanced', 'vocal-focus', 'punchy')
VARIANTS = ('original', 'gentle', 'firm')


def _valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def suggest_compression(metrics: dict, mix: str, intensity: str = 'natural') -> dict:
    """Prefer suitable processed PCM with clipping/overcompression safeguards.

    Ranking is based only on observed file statistics and selectable intensity.
    Original is always a valid fallback, especially for an unchanged Gentle.
    """
    if mix not in MIXES or intensity not in ('natural', 'balanced', 'punchy'):
        raise ValueError('Unsupported mix or intensity')
    original = metrics.get(mix + '/original')
    if not isinstance(original, dict) or not all(_valid_number(original.get(k)) for k in
            ('rms_dbfs','sample_peak_dbfs','crest_db')):
        return {'variant':'original', 'confidence':'low', 'reason':'Mesures WAV incomplètes : conserver Original.',
                'candidates':{}}
    # A high crest factor typically indicates more peak-vs-average dynamic range,
    # but does not alone prove a song needs compression.
    crest = float(original['crest_db'])
    target = {'natural':0.35, 'balanced':1.1, 'punchy':2.3}[intensity]
    if crest < 7:
        target *= 0.55
    elif crest > 15:
        target *= 1.15
    best = 'original'
    best_score = target * 0.65
    candidates = {'original': {'score':round(best_score,3), 'rms_delta_db':0.0,
                               'crest_delta_db':0.0, 'eligible':True}}
    for variant in ('gentle','firm'):
        row = metrics.get(mix + '/' + variant, {})
        if not isinstance(row, dict):
            continue
        if row.get('same_samples_as_original') is True:
            candidates[variant] = {'eligible':False, 'reason':'WAV identique à Original'}
            continue
        if not all(_valid_number(row.get(k)) for k in
                ('rms_dbfs','sample_peak_dbfs','crest_db','rms_delta_db',
                 'max_absolute_sample_difference')):
            candidates[variant] = {'eligible':False, 'reason':'Mesures de comparaison manquantes'}
            continue
        if float(row['max_absolute_sample_difference']) <= 0:
            candidates[variant] = {'eligible':False, 'reason':'Signal inchangé'}
            continue
        peak = float(row['sample_peak_dbfs'])
        crest_delta = crest - float(row['crest_db'])
        rms_delta = float(row['rms_delta_db'])
        # Failsafe: an increase in crest is not evidence of desired compression;
        # negative values are penalized. Substantial changes to a natural source
        # are discouraged; clipping/very flat signals are never recommended.
        if peak >= -0.1 or row['crest_db'] < 5 or abs(rms_delta) > 8 or crest_delta < -2:
            candidates[variant] = {'eligible':False,'reason':'Sécurité dynamique / niveau'}
            continue
        observed = max(0.0, crest_delta)
        score = abs(observed - target) + max(0.0, abs(rms_delta) - 3) * 0.35
        if variant == 'firm' and intensity == 'natural':
            score += 1.0
        candidates[variant] = {'eligible':True,'score':round(score,3),
                               'crest_delta_db':round(crest_delta,3),
                               'rms_delta_db':round(rms_delta,3)}
        if score + 0.08 < best_score:
            best, best_score = variant, score
    if best == 'original':
        reason = 'Original préserve mieux la dynamique pour cette intensité (selon les mesures WAV).'
    else:
        row = candidates[best]
        reason = (best.title() + ' correspond le mieux à la cible indicative : '
                  + str(row['crest_delta_db']) + ' dB de variation du crest factor. '
                  + 'Ce n’est PAS la réduction de gain Pro-C 3.')
    return {'variant':best,'confidence':'heuristic', 'intensity':intensity,
            'reason':reason, 'candidates':candidates,
            'note':'Suggestion mesurée, non musicale et non-Hermes. Aucun mastering autorisé sans ♥.'}
