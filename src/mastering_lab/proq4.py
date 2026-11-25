"""FabFilter Pro-Q 4 measured mapping, with readback validation.

From user's Pro-Q 4: freq normalized .575188=>1000Hz => 10..30000 log map;
gain normalized .6=> measured +6dB on 1kHz test signal => +/-30 dB map.
Host confirms parameter readback at runtime. No parameter index is trusted
without matching its name from inspect output.
"""
from __future__ import annotations
import math
import re

def frequency_normalized(hz: float) -> float:
    if not 10 <= hz <= 30000: raise ValueError('Frequency out of Pro-Q 4 range')
    return math.log(hz/10) / math.log(3000)

def gain_normalized(db: float) -> float:
    if not -30 <= db <= 30: raise ValueError('Gain out of range')
    return (db+30)/60

def index_of(params: list[dict], name: str) -> int:
    matches = [p for p in params if p.get('name') == name and p.get('automatable')]
    if len(matches) != 1: raise ValueError(f'Expected one automatable {name!r}; got {len(matches)}')
    return int(matches[0]['index'])

def build_changes(inspect: dict, suggestions: list[dict], min_db: float = 0.35,
                  max_bands: int = 7) -> list[tuple[int,float]]:
    if 'Pro-Q 4' not in inspect.get('name',''):
        raise ValueError('Expected FabFilter Pro-Q 4 instance')
    params = inspect.get('parameters', [])
    if not (1 <= max_bands <= 24): raise ValueError('max_bands must be 1..24')
    changes=[]; slot=0
    for s in suggestions:
        db=float(s['recommended_gain_db'])
        if abs(db) < min_db: continue
        slot += 1
        if slot > max_bands: break
        # Use unused bands only, leave pre-existing plugin state untouched if inspecting a preset.
        used_name=f'Band {slot} Used'
        found = [p for p in params if p.get('name')==used_name]
        if len(found)!=1 or found[0].get('text')!='Unused':
            raise ValueError(f'{used_name} is not unused; start with default/clean Pro-Q 4')
        changes.extend([
            (index_of(params,used_name),1.0),
            (index_of(params,f'Band {slot} Enabled'),1.0),
            (index_of(params,f'Band {slot} Frequency'),frequency_normalized(float(s['center_hz']))),
            (index_of(params,f'Band {slot} Gain'),gain_normalized(db)),
        ])
    return changes
