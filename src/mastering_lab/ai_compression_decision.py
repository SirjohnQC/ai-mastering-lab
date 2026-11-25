"""Guarded local Hermes3 recommendation of EXISTING compressed WAV variants.

The LLM may SELECT only from variants already rendered and approved as eligible
by deterministic PCM checks. It cannot propose VST parameters or approve masters.
Local Ollama receives numeric summaries ONLY: never audio paths or WAV content.
"""
from __future__ import annotations

import json
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .compression_advisor import suggest_compression

MIXES = ('balanced','vocal-focus','punchy')
INTENSITIES = ('natural','balanced','punchy')
VARIANTS = ('original','gentle','firm')
DECISION_SCHEMA = 1


def _safe_choice(metrics, reports, mix, intensity):
    scored = suggest_compression(metrics, mix, intensity)
    allowed = ['original']
    for variant in ('gentle','firm'):
        if (scored['candidates'].get(variant, {}).get('eligible')
                and not (variant == 'gentle' and
                         reports.get(mix, {}).get('smart_gentle', {}).get('status') == 'fallback_original')):
            allowed.append(variant)
    return scored, allowed


def _summarize(metrics, reports):
    """Pass only observed numeric evidence; paths and personal data excluded."""
    matrix = {}
    fallback = {}
    for mix in MIXES:
        for intensity in INTENSITIES:
            key = mix + '/' + intensity
            scored, allowed = _safe_choice(metrics,reports,mix,intensity)
            fallback[key] = {'selected':scored['variant'] if scored['variant'] in allowed else 'original',
                             'reason':scored['reason']}
            candidates = {}
            for variant in allowed:
                row = metrics.get(mix + '/' + variant, {})
                window = row.get('window_analysis', {})
                candidates[variant] = {
                    'rms_dbfs':row.get('rms_dbfs'),
                    'sample_peak_dbfs':row.get('sample_peak_dbfs'),
                    'crest_db':row.get('crest_db'),
                    'rms_delta_db':row.get('rms_delta_db', 0.0),
                    'loud_relative_to_quiet_db':window.get('loud_relative_to_quiet_db'),
                }
            matrix[key] = {'allowed':allowed,'candidates':candidates,
                           'pcm_advice':fallback[key]['selected']}
    return matrix,fallback


def _request_local(matrix, *, model='hermes3:8b', endpoint='http://127.0.0.1:11434', timeout=12):
    parsed = urlparse(endpoint)
    if (parsed.scheme != 'http' or parsed.hostname not in ('localhost','127.0.0.1','::1')
            or parsed.username or parsed.password or parsed.path not in ('','/')):
        raise ValueError('Only local Ollama may receive compression metrics.')
    system = (
        'You are a conservative music production decision assistant. '
        'Choose among already rendered compression WAV variants for each of exactly '
        'nine mix/intensity keys. Never invent gain reduction or claim to have '
        'heard audio. The numeric PCM data are not proof of artistic quality. '
        'Respect the allowed list PER key; Original is always permitted. '
        'Prefer subtle preservation for natural and modest dynamics control for punchy. '
        'Do not recommend an unavailable variant, invent DSP values, or propose parameter changes. '
        'Return ONLY strict JSON: {"choices":{"balanced/natural":{"selected":"original",'
        '"reason":"brief French reason"},...}}. All nine keys required. '
        'Each reason must be French, factual, no more than 160 characters.'
    )
    body = json.dumps({
        'model':model,'stream':False,'format':'json',
        'options':{'temperature':0,'num_predict':720},
        'messages':[{'role':'system','content':system},
                    {'role':'user','content':json.dumps(matrix,ensure_ascii=False)}]},
        ensure_ascii=False).encode('utf-8')
    req = Request(endpoint.rstrip('/')+'/api/chat',data=body,
                  headers={'Content-Type':'application/json'},method='POST')
    with urlopen(req,timeout=timeout) as response:
        envelope = json.loads(response.read(60000).decode('utf-8'))
    return json.loads(envelope['message']['content'])


def _validated(raw, matrix):
    if not isinstance(raw,dict) or not isinstance(raw.get('choices'),dict):
        raise ValueError('Hermes returned malformed choices.')
    choices = raw['choices']
    if set(choices) != set(matrix):
        raise ValueError('Hermes did not return exactly nine choices.')
    accepted = {}
    for key, row in choices.items():
        if not isinstance(row,dict) or set(row) != {'selected','reason'}:
            raise ValueError('Hermes returned an invalid choice shape.')
        variant = row['selected']
        reason = row['reason']
        if variant not in matrix[key]['allowed']:
            raise ValueError('Hermes selected an ineligible PCM variant: '+key)
        if not isinstance(reason,str) or not reason.strip() or len(reason.strip())>160:
            raise ValueError('Hermes reason missing or too long.')
        accepted[key] = {'selected':variant,'reason':' '.join(reason.split())}
    return accepted


def decide_compressions(metrics, reports, *, ask_fn=None, model='hermes3:8b', timeout=12):
    """One local request for all nine intents; safe deterministic fallback.

    If unavailable/untrusted model output, NONE of the nine choices is
    accidentally represented as Hermes. Caller always receives a valid matrix.
    """
    matrix, fallback = _summarize(metrics, reports)
    try:
        raw = ask_fn(matrix) if ask_fn else _request_local(matrix,model=model,timeout=timeout)
        choices = _validated(raw,matrix)
        mode, error = 'hermes', None
    except Exception as exc:
        choices, mode = fallback, 'pcm_fallback'
        error = f'{type(exc).__name__}: {exc}'
    return {'schema_version':DECISION_SCHEMA,'mode':mode,'model':model if mode=='hermes' else None,
            'choices':choices,'allowed':{key:item['allowed'] for key,item in matrix.items()},
            'warning':error,
            'limitations':'Only PCM metrics; no audio sent, no plugin parameter generation, no mastering approval.'}
