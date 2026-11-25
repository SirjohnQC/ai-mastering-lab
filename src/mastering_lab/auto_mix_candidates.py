"""Conservative, deterministic mix variants. No claims of AI listening or mastering."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import math

VARIANTS = ('balanced', 'vocal-focus', 'punchy')

def _group(track: dict) -> str:
    label = (str(track.get('category','')) + ' ' + Path(str(track['file'])).stem).lower()
    if any(w in label for w in ('vocal', 'voice', 'chant', 'vox')):
        return 'vocals'
    if any(w in label for w in ('drum', 'percussion', 'kick', 'snare')):
        return 'drums'
    if any(w in label for w in ('bass', 'basse')):
        return 'bass'
    if any(w in label for w in ('guitar', 'guitare')):
        return 'guitars'
    return 'other'

def candidate_configs(config: dict) -> dict[str,dict]:
    tracks = config.get('tracks')
    if not isinstance(tracks, list) or not tracks:
        raise ValueError('Aucun stem dans la configuration.')
    results = {}
    increments = {
        'balanced': {'vocals':0., 'drums':0., 'bass':0., 'guitars':0., 'other':0.},
        'vocal-focus': {'vocals':1., 'drums':-0.5, 'bass':-0.3, 'guitars':-0.5, 'other':-0.4},
        'punchy': {'vocals':0., 'drums':1., 'bass':0.6, 'guitars':-0.3, 'other':-0.3},
    }
    for name in VARIANTS:
        proposal = deepcopy(config)
        for t in proposal['tracks']:
            original = float(t.get('gain_db',0.))
            if not math.isfinite(original) or abs(original)>18:
                raise ValueError('Gain de stem hors limite.')
            delta = 0. if bool(t.get('mute',False)) else increments[name][_group(t)]
            t['gain_db'] = round(max(-18.,min(18.,original+delta)),2)
        proposal['auto_mix_variant'] = name
        results[name] = proposal
    return results
