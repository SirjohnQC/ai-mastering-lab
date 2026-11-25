"""Local opt-in A/B preference memory for EQ auditions.

Stores only the user's explicit decision and processing parameters, never audio.
"""
import json
from datetime import datetime, timezone
from pathlib import Path


def record_eq_choice(path, *, before, after, choice, moves, song=''):
    if choice not in ('before', 'after'):
        raise ValueError('Le choix doit être Avant ou Après.')
    original, audition = Path(before).resolve(), Path(after).resolve()
    if not original.is_file() or not audition.is_file():
        raise FileNotFoundError('Le WAV original ou son essai EQ est manquant.')
    path = Path(path)
    if path.is_file():
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, list):
            raise ValueError('Historique EQ invalide.')
    else:
        data = []
    record = {'date_utc':datetime.now(timezone.utc).isoformat(), 'song':str(song)[:160],
              'original':str(original), 'audition':str(audition),
              'preferred':choice, 'moves':moves}
    data.append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data[-500:], ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return len(data)


def summarize_eq_preferences(path, *, max_examples=8):
    """Small, bounded, strictly validated context for Hermes; no audio or source paths.

    A vote for 'before' rejects the *tested move*, it does not recommend its inverse.
    Only explicit user confirmations contribute; malformed entries are ignored.
    """
    if path is None or not Path(path).is_file():
        return None
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    examples = []
    votes = {'before': 0, 'after': 0}
    for record in data[-500:]:
        if not isinstance(record, dict) or record.get('preferred') not in votes:
            continue
        moves = record.get('moves')
        if not isinstance(moves, list) or not moves or len(moves) > 2:
            continue
        clean = []
        for item in moves:
            if not isinstance(item, dict):
                clean = []
                break
            # Accept applied-render reports with {'requested': {...}} as well as
            # older direct-move records. Never forward user-provided free text.
            m = item.get('requested', item)
            if not isinstance(m, dict):
                clean = []
                break
            try:
                band = m['band_index']
                frequency = float(m['frequency_hz'])
                gain = float(m['gain_db'])
            except (KeyError, ValueError, TypeError, OverflowError):
                clean = []
                break
            from .ai_fx_intelligence import BANDS, MAX_GAIN_DB
            import math
            if (type(band) is not int or band not in range(len(BANDS))
                    or not math.isfinite(frequency) or not math.isfinite(gain)
                    or not BANDS[band][0] <= frequency <= BANDS[band][1]
                    or not 0.1 <= abs(gain) <= MAX_GAIN_DB):
                clean = []
                break
            clean.append({'band_index': band, 'frequency_hz': round(frequency, 1),
                          'gain_db': round(gain, 2)})
        if not clean:
            continue
        choice = record['preferred']
        votes[choice] += 1
        examples.append({'preferred': choice, 'tested_moves': clean})
    if not examples:
        return None
    return {'total_confirmed': len(examples), 'accepted_after': votes['after'],
            'rejected_before': votes['before'],
            'recent_examples': examples[-min(max_examples, 12):],
            'interpretation': ('User confirmed preferences from A/B experiments only. '
                               'Before means the tested EQ was rejected, NOT that inverse EQ is preferred. '
                               'Examples may differ by song and cannot establish causal preference.')}
