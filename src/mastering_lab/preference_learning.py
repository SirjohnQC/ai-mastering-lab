"""Opt-in local preference history for A/B/C decisions.

This records explicit user confirmations, not automatically selected model results.
It is a small auditable example memory: no neural training or quality prediction.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
VARIANTS = ('balanced', 'vocal-focus', 'punchy')
MAX_EXAMPLES = 200
METRIC_KEYS = ('rms_dbfs', 'sample_peak_dbfs', 'crest_db', 'stereo_correlation')


def preference_path(root):
    return Path(root) / 'settings' / 'mix_preferences.json'


def load_preferences(path):
    path = Path(path)
    if not path.exists():
        return {'schema': SCHEMA, 'examples': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or not isinstance(data.get('examples'), list):
        raise ValueError('Historique de préférences incompatible.')
    return data


def _atomic_save(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, encoding='utf-8',
                                     prefix='.preferences-', suffix='.tmp', delete=False) as handle:
        temp = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def save_choice(path, *, selected, metrics, ai_suggested=None, song=None):
    if selected not in VARIANTS:
        raise ValueError('Variante non reconnue.')
    if not isinstance(metrics, dict) or set(metrics) != set(VARIANTS):
        raise ValueError('Mesures DSP des trois variantes requises.')
    checked = {}
    for variant in VARIANTS:
        item = metrics[variant]
        if not isinstance(item, dict):
            raise ValueError('Mesures DSP invalides.')
        checked[variant] = {}
        for key in METRIC_KEYS:
            value = item.get(key)
            if not isinstance(value, (float, int)) or isinstance(value, bool):
                raise ValueError('Mesures DSP manquantes.')
            import math
            if not math.isfinite(value):
                raise ValueError('Mesures DSP non finies.')
            checked[variant][key] = round(float(value), 4)
    entry = {'date_utc': datetime.now(timezone.utc).isoformat(),
             'selected': selected, 'ai_suggested': ai_suggested if ai_suggested in VARIANTS else None,
             'song': str(song or '')[:120], 'metrics': checked}
    data = load_preferences(path)
    data['examples'] = (data['examples'] + [entry])[-MAX_EXAMPLES:]
    _atomic_save(path, data)
    return len(data['examples'])


def preference_context(path):
    data = load_preferences(path)
    examples = data['examples'][-40:]
    if not examples:
        return None
    count = Counter(e['selected'] for e in examples if e.get('selected') in VARIANTS)
    chosen = [e['metrics'][e['selected']] for e in examples
              if e.get('selected') in VARIANTS and isinstance(e.get('metrics'), dict)
              and isinstance(e['metrics'].get(e['selected']), dict)]
    means = {}
    for key in METRIC_KEYS:
        vals = [float(m[key]) for m in chosen if isinstance(m.get(key), (int, float))]
        if vals:
            means[key] = round(sum(vals) / len(vals), 3)
    return {'count': len(examples), 'variant_counts': {k: count[k] for k in VARIANTS},
            'chosen_mix_metric_means': means,
            'caution': 'These are explicit past selections, not proof of objective audio quality. '
                       'Use as a weak preference signal; never override measured safety constraints.'}


def clear_preferences(path):
    _atomic_save(path, {'schema': SCHEMA, 'examples': []})
