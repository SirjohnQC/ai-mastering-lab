"""v0.19 — bounded, opt-in AI EQ audition for an existing stereo premix.

Never changes stems, original mix, plugin presets, or the master source.
Reference spectral profiles are weak hints; not target curves to force-match.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

BANDS = ((20, 60), (60, 120), (120, 250), (250, 500),
         (500, 2000), (2000, 5000), (5000, 10000), (10000, 20000))
MAX_MOVES = 2
MAX_GAIN_DB = 1.0


def validate_eq_proposal(raw, features, *, reference=None):
    """Reject unknown fields/large moves; a valid empty plan means 'no action'."""
    if not isinstance(raw, dict) or set(raw) != {'moves', 'summary'}:
        raise ValueError('Plan EQ: champs moves et summary requis, sans champs supplémentaires.')
    if not isinstance(raw['summary'], str) or not raw['summary'].strip():
        raise ValueError('Résumé de la proposition manquant.')
    moves = raw['moves']
    if not isinstance(moves, list) or len(moves) > MAX_MOVES:
        raise ValueError('Maximum deux corrections EQ.')
    shares = features.get('spectral_shares')
    if not isinstance(shares, (list, tuple)) or len(shares) != len(BANDS):
        raise ValueError('Analyse spectrale indisponible.')
    clean = []
    seen = set()
    for move in moves:
        if not isinstance(move, dict) or set(move) != {'band_index', 'frequency_hz', 'gain_db', 'reason'}:
            raise ValueError('Correction EQ: bande, fréquence, gain et justification requis.')
        band = move['band_index']
        if isinstance(band, bool) or not isinstance(band, int) or band not in range(len(BANDS)) or band in seen:
            raise ValueError('Bande EQ invalide ou répétée.')
        seen.add(band)
        freq, gain = move['frequency_hz'], move['gain_db']
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (freq, gain)):
            raise ValueError('Fréquence ou gain EQ non numérique.')
        if not (BANDS[band][0] <= freq <= BANDS[band][1]) or not (0.1 <= abs(gain) <= MAX_GAIN_DB):
            raise ValueError('Correction EQ hors bande ou gain trop important.')
        if not isinstance(move['reason'], str) or len(move['reason'].strip()) < 8:
            raise ValueError('Justification EQ absente.')
        clean.append({'band_index':band, 'frequency_hz':round(float(freq), 1),
                      'gain_db':round(float(gain), 2), 'reason':move['reason'].strip()[:240],
                      'measured_share':round(float(shares[band]), 6)})
    return {'moves':clean, 'summary':raw['summary'].strip()[:500],
            'mode':'hermes', 'limitations': 'EQ d’essai sur le prémix entier seulement; mesures FFT échantillonnées, pas une preuve de défaut audible.'}


def request_eq_proposal(features, reference=None, *, eq_preferences=None, model='hermes3:8b', requester=None, timeout=60, creative=False):
    """Only local Ollama; injectable requester for deterministic tests."""
    system = (
        'You are proposing an OPTIONAL EQ listening experiment on one stereo premix, NOT stems. '
        'You cannot hear it; FFT spectral shares are descriptive, not evidence of a defect. '
        'The reference average is weak context, never a target to match blindly. '
        'Confirmed EQ preferences describe user-approved A/B tests, NOT proof of a technical fault. '
        'For a rejected change, do not infer that the inverse EQ would be preferred. '
        'Preference counts are weak evidence, never override measured safety limits. ' +
        ('For an optional CREATIVE experiment, propose one or two subtle and reversible listening variations if plausible; do not invent measurable defects. ' if creative else 'Prefer zero moves unless the data justify a small experiment. ') +
        'Return ONLY JSON with exactly keys summary and moves. moves is an array of 0 to 2 items '
        'with exactly band_index (0..7), frequency_hz (within the chosen band), gain_db (-1.0 to +1.0, abs >= 0.1), '
        'reason (short French explanation, state uncertainty). No compressor settings, no assertions of listening. '
        f'Bands Hz (index 0..7): {BANDS}.'
    )
    payload = {'model':model, 'stream':False, 'think':False, 'format':'json',
               'options':{'temperature':0, 'num_predict':500},
               'messages':[{'role':'system', 'content':system},
                           {'role':'user','content':json.dumps({'premix_features':features,
                                                               'reference_context':reference,
                                                               'confirmed_eq_preferences':eq_preferences},ensure_ascii=False)}]}
    if requester is None:
        def requester(body):
            req = Request('http://127.0.0.1:11434/api/chat',
                          data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                          headers={'Content-Type':'application/json'}, method='POST')
            with urlopen(req, timeout=timeout) as res:
                return json.loads(res.read(100000).decode('utf-8'))
    envelope = requester(payload)
    if not isinstance(envelope, dict) or envelope.get('done_reason') == 'length':
        raise ValueError('Hermes a épuisé sa limite de réponse.')
    content = envelope.get('message', {}).get('content', '')
    if not isinstance(content, str) or not content.strip():
        raise ValueError('Hermes a retourné une réponse vide.')
    return validate_eq_proposal(json.loads(content), features, reference=reference)


def propose_for_wav(wav_path, *, reference_path=None, eq_preferences_path=None, requester=None, creative=False):
    from .reference_learning import extract_features, load_active_context
    wav_path = Path(wav_path).resolve()
    features = extract_features(wav_path)
    reference = load_active_context(reference_path) if reference_path else None
    from .eq_feedback import summarize_eq_preferences
    preferences = summarize_eq_preferences(eq_preferences_path) if eq_preferences_path else None
    result = request_eq_proposal(features, reference, eq_preferences=preferences,
                                 requester=requester, creative=creative)
    result['eq_preference_context'] = preferences
    result['source'] = str(wav_path)
    result['source_signature'] = _signature(wav_path)
    result['source_features'] = features
    result['reference_used'] = bool(reference)
    return result


def _signature(path):
    stat = Path(path).stat()
    return [str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns]


def render_approved_eq(wav_path, plan, *, root, plugin=None, host=None, runner=None, progress=None):
    """Render separate Pro-Q4 audition *only after caller's explicit approval*.

    Uses existing strict legacy Pro-Q calibration. No Pro-C compression automation.
    """
    import numpy as np
    import soundfile as sf
    from .eq_audition import _calibrate_frequency, _verify_layout, _hz_text, _db_text
    from .host import run_host
    source = Path(wav_path).resolve()
    if not source.is_file() or str(source) != plan.get('source') or _signature(source) != plan.get('source_signature'):
        raise ValueError('Source modifiée depuis la proposition. Relancer l’analyse IA.')
    proposal = validate_eq_proposal({'summary':plan.get('summary'), 'moves':[
        {k:m[k] for k in ('band_index', 'frequency_hz', 'gain_db', 'reason')} for m in plan.get('moves', [])
    ]}, plan.get('source_features', {}))
    if not proposal['moves']:
        raise ValueError('Aucune correction à appliquer.')
    root = Path(root).resolve()
    host = Path(host or root/'native/build/mastering-host_artefacts/Release/mastering-host.exe').resolve()
    plugin = Path(plugin or 'C:/Program Files/Common Files/VST3/FabFilter/FabFilter Pro-Q 4.vst3').resolve()
    if not host.is_file() or not plugin.exists() or plugin.suffix.lower() != '.vst3':
        raise FileNotFoundError('JUCE mastering-host.exe ou FabFilter Pro-Q 4.vst3 introuvable.')
    meta = sf.info(str(source))
    if meta.channels != 2 or meta.frames < 1:
        raise ValueError('Un prémix WAV stéréo est requis.')
    fn = runner or run_host
    info = fn(host, 'inspect', plugin=plugin, timeout=90)
    _verify_layout(info)
    target = source.parent/'ai-fx-auditions'
    target.mkdir(parents=True, exist_ok=True)
    index = 1
    while (target/f'{source.stem}-ai-eq-{index:03d}.wav').exists():
        index += 1
    final = target/f'{source.stem}-ai-eq-{index:03d}.wav'
    applied = []
    with tempfile.TemporaryDirectory(prefix='aml-ai-fx-') as td:
        work = Path(td)
        current = source
        for i, move in enumerate(proposal['moves']):
            if progress:
                progress(f'Calibrage Pro-Q 4 {i+1}/{len(proposal["moves"])}')
            norm, measured_hz = _calibrate_frequency(host, plugin, meta.samplerate,
                                                     move['frequency_hz'], work, fn)
            norm_gain = .5 + move['gain_db']/60.0
            output = work/f'processed-{i}.wav'
            if progress:
                progress(f'Rendu EQ {i+1}/{len(proposal["moves"])}')
            rendered = fn(host, 'render', plugin=plugin, input_file=current,
                          output_file=output,
                          parameter_changes=[(0, 1.0), (2, norm), (3, norm_gain)], timeout=600)
            changes = {x['index']:x for x in rendered.get('parameter_changes', [])}
            if not {0,2,3}.issubset(changes):
                raise ValueError('Pro-Q 4 n’a pas confirmé tous les paramètres.')
            freq_actual = _hz_text(changes[2].get('text',''))
            gain_actual = _db_text(changes[3].get('text',''))
            if not math.isclose(freq_actual, move['frequency_hz'], rel_tol=.035, abs_tol=2) or abs(gain_actual-move['gain_db'])>.16:
                raise ValueError('Pro-Q 4 a appliqué une valeur inattendue. Rendu refusé.')
            check = sf.info(str(output))
            if (check.channels, check.frames, check.samplerate) != (2, meta.frames, meta.samplerate):
                raise ValueError('Durée, canaux ou fréquence modifiés par le VST.')
            if int(rendered.get('tail_samples',0) or 0):
                raise ValueError('Queue VST inattendue; synchronisation non garantie.')
            applied.append({'requested':move, 'actual_frequency_hz':freq_actual, 'actual_gain_db':gain_actual})
            current = output
        tmp = final.with_suffix('.partial')
        try:
            shutil.copyfile(current, tmp)
            if final.exists():
                raise FileExistsError('Nom de sortie déjà présent; aucun fichier écrasé.')
            tmp.replace(final)
        finally:
            tmp.unlink(missing_ok=True)
    report = {'status':'ok', 'original':str(source), 'after':str(final), 'moves':applied,
              'plugin':str(plugin), 'source_signature':plan['source_signature'],
              'warning':'Essai EQ non masterisé; écouter à volume égalisé avant de l’adopter. Aucun master n’est remplacé.'}
    final.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
