"""Conservative, auditable selection among already-rendered album candidates.

Measured sample peaks/RMS are authoritative. The local LLM may propose a winner,
but cannot invent DSP results, override safety checks or modify audio here.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from urllib.request import Request, urlopen

CANDIDATES = ('balanced', 'vocal-focus', 'punchy')
MAX_SAMPLE_PEAK_DBFS = -0.05


def analyze_candidate(path, *, block_frames=131072):
    """Streaming full-file sample peak, RMS, crest and stereo correlation.

    These are NOT integrated LUFS, intersample true peak, or subjective quality.
    """
    import numpy as np
    import soundfile as sf

    path = Path(path)
    with sf.SoundFile(str(path)) as wav:
        if wav.channels != 2:
            raise ValueError(f'WAV stéréo requis : {path.name}')
        if len(wav) == 0:
            raise ValueError(f'WAV vide : {path.name}')
        frames = 0
        sum_squares = 0.0
        sample_peak = 0.0
        l2 = r2 = lr = 0.0
        for block in wav.blocks(blocksize=block_frames, dtype='float64', always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError(f'Échantillons non numériques : {path.name}')
            frames += len(block)
            sum_squares += float(np.square(block).sum())
            sample_peak = max(sample_peak, float(np.abs(block).max()))
            left, right = block[:, 0], block[:, 1]
            l2 += float(np.dot(left, left))
            r2 += float(np.dot(right, right))
            lr += float(np.dot(left, right))
        rate = wav.samplerate
    if frames == 0:
        raise ValueError(f'WAV vide : {path.name}')
    rms = math.sqrt(sum_squares / (frames * 2))
    peak_dbfs = 20 * math.log10(max(sample_peak, 1e-12))
    rms_dbfs = 20 * math.log10(max(rms, 1e-12))
    return {
        'sample_peak_dbfs': round(peak_dbfs, 3),
        'rms_dbfs': round(rms_dbfs, 3),
        'crest_db': round(peak_dbfs - rms_dbfs, 3),
        'stereo_correlation': round(max(-1.0, min(1.0, lr / max(math.sqrt(l2*r2), 1e-18))), 4),
        'duration_seconds': round(frames / rate, 3),
        'sample_rate': int(rate),
        'channels': 2,
        'sample_peak_clipped': bool(sample_peak >= 1.0),
    }


def measure_candidates(paths, *, analyzer=None):
    if set(paths) != set(CANDIDATES):
        raise ValueError('Trois variantes requises')
    fn = analyzer or analyze_candidate
    result = {name: fn(paths[name]) for name in CANDIDATES}
    rates = {value['sample_rate'] for value in result.values()}
    durations = [value['duration_seconds'] for value in result.values()]
    if len(rates) != 1 or max(durations) - min(durations) > 0.1:
        raise ValueError('Variantes incompatibles : durée ou fréquence différente')
    return result


def request_selection(metrics, *, reference=None, preferences=None, model='hermes3:8b', endpoint='http://127.0.0.1:11434', timeout=40):
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username or parsed.password:
        raise ValueError('Le modèle doit être servi par Ollama local.')
    prompt = (
        'You are choosing between three premixed songs. DSP data are facts, but do NOT ' 
        'infer or invent whole-track LUFS, true peak, genre, listening impressions, or spectral ' 
        'properties from these metrics. Select a conservative candidate, considering crest, RMS, '
        'sample peaks and correlation; volume alone is not quality. '
        'Return ONLY JSON with exactly keys "selected" and "reason". "selected" must be one of '
        '"balanced", "vocal-focus", "punchy". "reason" must be a short explanation in French '
        '(max 240 characters) based only on the supplied measurements, not invented listening impressions. '
        'When reference data exist, consider sampled relative spectrum as a weak preference, not a quality metric. '
        'When preferences exist, treat confirmed past user choices as a WEAK preference, never a safety rule. '
        'Never claim you listened to any audio or that two songs sound alike.'
    )
    payload = json.dumps({'model': model, 'stream': False, 'format': 'json',
                          'options': {'temperature': 0, 'num_predict': 190},
                          'messages': [{'role':'system', 'content':prompt},
                                       {'role':'user', 'content':json.dumps({'candidates': metrics, 'reference': reference, 'user_preferences': preferences}, ensure_ascii=False)}]},
                         ensure_ascii=False).encode('utf-8')
    req = Request(endpoint.rstrip('/') + '/api/chat', data=payload,
                  headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(req, timeout=timeout) as response:
        envelope = json.loads(response.read(50_000).decode('utf-8'))
    raw = envelope['message']['content']
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('Réponse Hermes vide')
    return json.loads(raw)


def normalize_variant(value):
    """Allow cosmetic LLM spelling variations, never guess an unknown candidate."""
    if not isinstance(value, str):
        raise ValueError('Sélection Hermes : variante non textuelle')
    plain = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    plain = re.sub(r'[^a-z0-9]+', '-', plain.casefold()).strip('-')
    variants = {'balanced': 'balanced', 'balance': 'balanced',
                'vocal-focus': 'vocal-focus', 'vocalfocus': 'vocal-focus',
                'punchy': 'punchy'}
    if plain not in variants:
        raise ValueError(f'Sélection Hermes : variante inconnue ({value[:70]!r})')
    return variants[plain]


def validate_selection(proposal, metrics):
    if not isinstance(proposal, dict) or 'selected' not in proposal or 'reason' not in proposal:
        raise ValueError('Sélection Hermes : structure invalide (selected/reason requis)')
    selected = normalize_variant(proposal['selected'])
    reason = proposal['reason']
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Sélection Hermes : justification absente')
    # Long explanations are a presentation issue, not an audio-safety issue.
    reason = ' '.join(reason.split())
    if len(reason) > 240:
        reason = reason[:239].rstrip() + '…'
    candidate = metrics[selected]
    if candidate['sample_peak_clipped'] or candidate['sample_peak_dbfs'] >= MAX_SAMPLE_PEAK_DBFS:
        raise ValueError(f'{selected} refusé : crêtes à risque')
    if candidate['stereo_correlation'] < -0.25:
        raise ValueError(f'{selected} refusé : corrélation stéréo fortement négative')
    if not (-70 < candidate['rms_dbfs'] <= 0) or not (0 <= candidate['crest_db'] < 70):
        raise ValueError(f'{selected} refusé : mesures DSP suspectes')
    return {'selected': selected, 'reason': reason.strip()}


def choose_candidate(paths, *, analyzer=None, ask_fn=None, model='hermes3:8b', enabled=True, reference_path=None, preferences_path=None):
    """On any measurement, model, or validation failure, master Balanced.

    Safety checks apply to AI choices; Balanced fallback is still inspected by
    downstream mastering/QC, not presumed safe or aesthetically good.
    """
    metrics = None
    try:
        metrics = measure_candidates(paths, analyzer=analyzer)
        if not enabled:
            raise ValueError('Sélection IA désactivée')
        reference = None
        if reference_path is not None:
            from .reference_learning import load_active_context, extract_features
            reference = load_active_context(reference_path)
            if reference:
                # The reference is NOT a direct measure of candidate quality.
                # Give Hermes comparable relative spectral measurements for each WAV.
                candidate_profiles = {key: extract_features(paths[key])['spectral_shares']
                                      for key in CANDIDATES}
                reference = {**reference, 'candidate_spectral_shares': candidate_profiles}
        preferences = None
        if preferences_path is not None:
            from .preference_learning import preference_context
            try:
                preferences = preference_context(preferences_path)
            except (OSError, ValueError, KeyError, TypeError):
                preferences = None  # Damaged optional preference memory must not block audio.
        proposal = (ask_fn or (lambda m: request_selection(m, reference=reference, preferences=preferences, model=model)))(metrics)
        chosen = validate_selection(proposal, metrics)
        return chosen['selected'], {'mode':'hermes', 'model':model, 'metrics':metrics,
                                    'selected':chosen['selected'], 'reason':chosen['reason'],
                                    'reference_used': bool(reference), 'reference': reference, 'preferences_used': bool(preferences),
                                    'limitations':'Full-file RMS/sample peak/crest/correlation only; no LUFS/true peak or listening evaluation.'}
    except Exception as exc:
        return 'balanced', {'mode':'fallback', 'selected':'balanced', 'metrics':metrics,
                            'reason':f'{type(exc).__name__}: {exc}',
                            'limitations':'Balanced fallback; not an AI ranking or mastered-audio QC pass.'}
