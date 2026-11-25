"""Explicit, non-destructive selection of individual stem audio files."""
from __future__ import annotations
from pathlib import Path

SUPPORTED = {'.wav', '.flac', '.aif', '.aiff', '.mp3'}

def selection_config(paths: list[Path]) -> dict:
    from .stem_inspector import classify_stem
    if not paths:
        raise ValueError('Choisis au moins un fichier audio.')
    resolved=[Path(p).resolve() for p in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError('Un même fichier a été sélectionné deux fois.')
    for p in resolved:
        if not p.is_file(): raise ValueError(f'Fichier absent: {p}')
        if p.suffix.lower() not in SUPPORTED: raise ValueError(f'Format non pris en charge: {p.name}')
    # File-level selection does not imply that mismatched files are sample-aligned.
    return {'schema_version':1,'selection_mode':'files',
            'description':'Only explicitly selected stems. Originals remain unchanged.',
            'tracks':[{'file':str(p),'category':classify_stem(p),
                       'gain_db':0.0,'pan':0.0,'mute':False,'eq':False} for p in resolved]}
