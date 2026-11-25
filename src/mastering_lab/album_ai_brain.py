"""Constrained, *optional* Hermes album mix decisions.

DSP measurements are authoritative. The language model may propose ONLY small,
per-group gain offsets for three already-defined candidates. No VST automation,
model training, or full artistic mastering is implied by this module.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
from urllib.request import Request, urlopen

GROUPS = ('vocals', 'drums', 'bass', 'guitars', 'other')
VARIANTS = ('balanced', 'vocal-focus', 'punchy')
LIMIT_DB = 1.0


def measure_stems(config: dict, *, max_seconds: float = 12.0) -> list[dict]:
    """Read evenly spaced chunks across each stem; no full-track RAM load.

    RMS and peak are measured on sampled windows, not claimed as full-song LUFS
    or true-peak measurements. Silence is handled explicitly.
    """
    import numpy as np
    import soundfile as sf
    from .auto_mix_candidates import _group

    output = []
    for track in config['tracks']:
        path = Path(track['file'])
        with sf.SoundFile(str(path)) as wav:
            if wav.channels not in (1, 2):
                raise ValueError(f'Nombre de canaux non pris en charge : {path.name}')
            rate = wav.samplerate
            length = len(wav)
            block_len = max(1, min(length, int(min(2.0, max_seconds / 6) * rate)))
            windows = []
            if length:
                for j in range(6):
                    start = int((length - block_len) * j / 5)
                    wav.seek(start)
                    windows.append(wav.read(block_len, dtype='float32', always_2d=True))
        if not windows:
            output.append({'file': path.name, 'group': _group(track), 'sampled_rms_dbfs': -120.0,
                           'sampled_peak_dbfs': -120.0, 'sampled_centroid_hz': 0.0})
            continue
        samples = np.concatenate(windows, axis=0)
        if not np.isfinite(samples).all():
            raise ValueError(f'Samples non numériques : {path.name}')
        mono = samples.mean(axis=1).astype('float64')
        rms = float(np.sqrt(np.mean(np.square(samples, dtype='float64'))))
        peak = float(np.max(np.abs(samples)))
        # FFT from a bounded window; useful only as a rough descriptive metric.
        segment = mono[:min(len(mono), 32768)]
        if len(segment) >= 16:
            spectrum = np.abs(np.fft.rfft(segment * np.hanning(len(segment))))
            freqs = np.fft.rfftfreq(len(segment), 1.0 / rate)
            centroid = float(np.sum(freqs * spectrum) / max(float(np.sum(spectrum)), 1e-18))
        else:
            centroid = 0.0
        output.append({'file': path.name, 'group': _group(track),
                       'sampled_rms_dbfs': round(20 * math.log10(max(rms, 1e-6)), 2),
                       'sampled_peak_dbfs': round(20 * math.log10(max(peak, 1e-6)), 2),
                       'sampled_centroid_hz': round(centroid, 1)})
    return output


def request_hermes(measurements: list[dict], *, model='hermes3:8b',
                   endpoint='http://127.0.0.1:11434', timeout=45) -> dict:
    """Ask local Ollama for gain proposals, not measurements or tool calls."""
    # Explicitly restrict the endpoint to loopback, to avoid sending stems data
    # to a remote host if a configuration is accidentally edited.
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Seul un serveur Ollama local est permis pour le mode Album.')
    system = (
        'You are a conservative audio assistant. The supplied measurements are approximate sampled '
        'DSP statistics, NOT whole-track LUFS. Never invent measurements. '
        'Return ONLY one JSON object with key "variants", containing keys "balanced", '
        '"vocal-focus", "punchy". For each variant supply exactly keys vocals, drums, bass, guitars, '
        'other, each a finite number between -1.0 and 1.0 representing gain offset in dB. '
        'Never return recommendations for plugins, EQ, pans, source changes, or filenames. '
        'Keep balanced subtle; vocal-focus should emphasize vocals relative to other groups, '
        'and punchy should emphasize drums+bass. No markdown.'
    )
    body = json.dumps({'model': model, 'stream': False, 'format': 'json',
                       'options': {'temperature': 0, 'num_predict': 320},
                       'messages': [{'role':'system', 'content':system},
                                    {'role':'user','content':json.dumps(measurements, ensure_ascii=False)}]},
                      ensure_ascii=False).encode('utf-8')
    req = Request(endpoint.rstrip('/') + '/api/chat', data=body,
                  headers={'Content-Type':'application/json'}, method='POST')
    with urlopen(req, timeout=timeout) as response:
        envelope = json.loads(response.read(150_000).decode('utf-8'))
    raw = envelope['message']['content']
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('Réponse Hermes vide')
    return json.loads(raw)


def validate_plan(payload: dict) -> dict:
    """Reject untrusted or ambiguous model outputs rather than clamp bad values."""
    if not isinstance(payload, dict) or set(payload) != {'variants'}:
        raise ValueError('Plan IA : structure racine invalide')
    variants = payload['variants']
    if not isinstance(variants, dict) or set(variants) != set(VARIANTS):
        raise ValueError('Plan IA : variantes incomplètes')
    result = {}
    for name in VARIANTS:
        values = variants[name]
        if not isinstance(values, dict) or set(values) != set(GROUPS):
            raise ValueError(f'Plan IA : groupes incorrects dans {name}')
        cleaned = {}
        for key, val in values.items():
            if isinstance(val, bool) or not isinstance(val, (int,float)) or not math.isfinite(val) or abs(val) > LIMIT_DB:
                raise ValueError(f'Plan IA : gain non sécuritaire {name}/{key}')
            cleaned[key] = round(float(val), 2)
        result[name] = cleaned
    if result['vocal-focus']['vocals'] <= max(result['vocal-focus'][k] for k in GROUPS if k != 'vocals'):
        raise ValueError('Plan IA : Vocal Focus sans priorité vocale')
    if (result['punchy']['drums'] + result['punchy']['bass']) / 2 <= (result['punchy']['guitars'] + result['punchy']['other']) / 2:
        raise ValueError('Plan IA : Punchy sans priorité rythmique')
    return result


def apply_plan(config: dict, plan: dict) -> dict:
    from .auto_mix_candidates import _group
    result = {}
    for name in VARIANTS:
        candidate = deepcopy(config)
        for track in candidate['tracks']:
            previous = float(track.get('gain_db', 0.0))
            if not math.isfinite(previous) or abs(previous) > 18:
                raise ValueError('Gain source hors limite')
            offset = 0.0 if track.get('mute', False) else plan[name][_group(track)]
            track['gain_db'] = round(max(-18.0, min(18.0, previous + offset)), 2)
        candidate['auto_mix_variant'] = name
        candidate['ai_gain_plan'] = True
        result[name] = candidate
    return result


def choose_configs(config: dict, *, ask_fn=None, analyzer=None, model='hermes3:8b', enabled=True):
    """Fail closed to deterministic variants, recording *why* AI was not used."""
    from .auto_mix_candidates import candidate_configs
    if not enabled:
        return candidate_configs(config), {'mode':'fallback', 'reason':'IA désactivée'}
    measurements = None
    try:
        measurements = (analyzer or measure_stems)(config)
        payload = (ask_fn or (lambda data: request_hermes(data, model=model)))(measurements)
        plan = validate_plan(payload)
        return apply_plan(config, plan), {
            'mode':'hermes', 'model':model, 'measurements':measurements,
            'plan':plan, 'limitations':'Only constrained stem group gain offsets; no auto FX or model learning.'}
    except Exception as exc:
        # Do not hide the fallback: manifests and QC report display the reason.
        return candidate_configs(config), {'mode':'fallback', 'reason':f'{type(exc).__name__}: {exc}',
                                           'measurements':measurements}
