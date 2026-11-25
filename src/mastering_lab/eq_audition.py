"""Real Pro-Q 4 offline EQ audition; no modification of the source WAV.

This module requires the user's existing JUCE mastering-host executable and Pro-Q 4.
It intentionally fails closed when its known parameter layout or host-reported
parameter text does not agree with the requested correction.
"""
from __future__ import annotations
import json
import math
import re
import tempfile
from pathlib import Path
import soundfile as sf
import numpy as np

from .eq_plan import BANDS, validate_plan


def _db_text(text: str) -> float:
    match = re.search(r'([-+]?\d+(?:[.,]\d+)?)\s*dB\b', str(text), re.I)
    if not match:
        raise ValueError(f'Pro-Q 4 ne confirme pas le gain en dB : {text!r}')
    return float(match.group(1).replace(',', '.'))


def _hz_text(text: str) -> float:
    s = str(text).replace(' ', '').replace(',', '.')
    match = re.search(r'([-+]?\d+(?:\.\d+)?)(kHz|Hz)', s, re.I)
    if not match:
        raise ValueError(f'Pro-Q 4 ne confirme pas la fréquence en Hz : {text!r}')
    return float(match.group(1)) * (1000 if match.group(2).lower() == 'khz' else 1)


def _verify_layout(info):
    if 'pro-q 4' not in str(info.get('name', '')).lower():
        raise ValueError('Seul FabFilter Pro-Q 4 est pris en charge pour cet essai.')
    params = info.get('parameters', [])
    expected = {0: ('enable', 'on', 'active'), 2: ('frequency', 'freq'), 3: ('gain',)}
    for idx, names in expected.items():
        if idx >= len(params) or int(params[idx].get('index', -1)) != idx:
            raise ValueError(f'Pro-Q 4: paramètre {idx} introuvable.')
        if not params[idx].get('automatable'):
            raise ValueError(f'Pro-Q 4: paramètre {idx} non automatisable.')
        name = str(params[idx].get('name', '')).lower()
        if not any(token in name for token in names):
            raise ValueError(f'Pro-Q 4: index {idx} inattendu ({name!r}). Aucun réglage envoyé.')


def _probe(host, plugin, probe_wav, out, norm, run_host):
    result = run_host(host, 'render', plugin=plugin, input_file=probe_wav,
                      output_file=out, parameter_changes=[(0, 1.0), (2, norm), (3, 0.5)], timeout=90)
    changes = {x['index']: x for x in result.get('parameter_changes', [])}
    if 2 not in changes:
        raise ValueError('Le host n’a pas confirmé la fréquence appliquée.')
    return _hz_text(changes[2].get('text', ''))


def _calibrate_frequency(host, plugin, source_rate, target_hz, tempdir, run_host):
    """Binary-search actual plugin display text; never assume its normalized scale."""
    # A tiny stereo silence file is enough to obtain the plugin's actual text.
    probe = tempdir / 'probe.wav'
    sf.write(str(probe), np.zeros((max(1024, source_rate // 30), 2), dtype=np.float32), source_rate)
    output = tempdir / 'probe-output.wav'
    lo, hi = 0.0, 1.0
    # Avoid evaluating extreme endpoints (some VSTs quantize there).
    for _ in range(12):
        mid = (lo + hi) / 2
        actual = _probe(host, plugin, probe, output, mid, run_host)
        if actual < target_hz:
            lo = mid
        else:
            hi = mid
    mid = (lo + hi) / 2
    actual = _probe(host, plugin, probe, output, mid, run_host)
    if not math.isclose(actual, target_hz, rel_tol=0.035, abs_tol=2.0):
        raise ValueError(f'Impossible de calibrer {target_hz:g} Hz : Pro-Q 4 indique {actual:g} Hz.')
    return mid, actual


def render_eq_audition(comparison, plan, *, root, plugin=None, host=None, runner=None, progress=None):
    """Render a separately named WAV and sidecar JSON (source remains intact).

    Host is checked at run time, not inferred from fixed plugin normalization.
    Multiple EQ suggestions are rendered as successive Pro-Q instances, each
    starting from a default blank plugin state; this avoids touching saved FX.
    """
    from .mix_comparison import load_comparison
    from .host import run_host
    from .mix_evaluator import evaluate_comparison
    root = Path(root).resolve()
    host = Path(host or root / 'native/build/mastering-host_artefacts/Release/mastering-host.exe').resolve()
    plugin = Path(plugin or 'C:/Program Files/Common Files/VST3/FabFilter/FabFilter Pro-Q 4.vst3').resolve()
    if not host.is_file():
        raise FileNotFoundError(f'JUCE mastering-host introuvable : {host}')
    if not plugin.exists() or plugin.suffix.lower() != '.vst3':
        raise FileNotFoundError(f'FabFilter Pro-Q 4 introuvable : {plugin}')
    paths, _ = load_comparison(comparison)
    before = paths['balanced']
    metrics = evaluate_comparison(comparison)
    clean = validate_plan({'moves': plan.get('moves')}, metrics)
    if not clean['moves']:
        raise ValueError('Hermes n’a proposé aucune correction EQ à essayer.')
    runner = runner or run_host
    info = runner(host, 'inspect', plugin=plugin, timeout=90)
    _verify_layout(info)
    meta = sf.info(str(before))
    if meta.channels != 2:
        raise ValueError('Le rendu Pro-Q 4 exige un WAV stéréo.')
    output_dir = before.parent / 'eq-auditions'
    output_dir.mkdir(parents=True, exist_ok=True)
    # Version the output: never replace a previous audition or any original.
    index = 1
    while (output_dir / f'balanced-eq-{index:03d}.wav').exists():
        index += 1
    final_path = output_dir / f'balanced-eq-{index:03d}.wav'
    report_path = final_path.with_suffix('.json')
    details = []
    with tempfile.TemporaryDirectory(prefix='aml-eq-audition-') as td:
        tempdir = Path(td)
        current = before
        for i, move in enumerate(clean['moves']):
            if progress:
                progress(f'Calibrage Pro-Q 4 — correction {i+1}/{len(clean["moves"])}')
            norm, hz = _calibrate_frequency(host, plugin, meta.samplerate,
                                             move['frequency_hz'], tempdir, runner)
            # Pro-Q 4 legacy host calibration: normalized 0.6 was observed as +6 dB.
            # Confirm the actual gain via the plugin's parameter_changes text.
            norm_gain = 0.5 + move['gain_db'] / 60.0
            candidate = tempdir / f'eq-{i}.wav'
            if progress:
                progress(f'Rendu Pro-Q 4 — correction {i+1}/{len(clean["moves"])}')
            result = runner(host, 'render', plugin=plugin, input_file=current,
                            output_file=candidate,
                            parameter_changes=[(0, 1.0), (2, norm), (3, norm_gain)], timeout=600)
            changed = {entry['index']: entry for entry in result.get('parameter_changes', [])}
            if not {0, 2, 3}.issubset(changed):
                raise ValueError('Le host n’a pas confirmé tous les paramètres Pro-Q 4.')
            gain_actual = _db_text(changed[3].get('text', ''))
            freq_actual = _hz_text(changed[2].get('text', ''))
            if abs(gain_actual - move['gain_db']) > 0.16:
                raise ValueError(f'Gain Pro-Q différent : {gain_actual:g} dB au lieu de {move["gain_db"]:g} dB')
            if not math.isclose(freq_actual, move['frequency_hz'], rel_tol=0.035, abs_tol=2.0):
                raise ValueError(f'Fréquence Pro-Q différente : {freq_actual:g} Hz')
            actual = sf.info(str(candidate))
            if (actual.frames, actual.samplerate, actual.channels) != (meta.frames, meta.samplerate, 2):
                raise ValueError(f'Durée/canaux inattendus : {actual.frames} vs {meta.frames}. Rendu refusé.')
            if int(result.get('tail_samples', 0) or 0) != 0:
                raise ValueError('Pro-Q a déclaré une queue audio. Rendu refusé pour préserver la synchronisation.')
            details.append({'requested':move, 'actual_frequency_hz':freq_actual, 'actual_gain_db':gain_actual})
            current = candidate
        # Atomic commit after all validations. No overwrite of source or older trial.
        import shutil
        staging = final_path.with_suffix('.wav.partial')
        try:
            shutil.copyfile(current, staging)
            staging.replace(final_path)
        finally:
            staging.unlink(missing_ok=True)
    report = {'status':'ok','kind':'eq_audition','original':str(before),'after':str(final_path),
              'plugin':str(plugin),'host':str(host),'moves':details,
              'note':'Vrai Pro-Q 4 JUCE hors ligne; audition non masterisée; originaux intacts'}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding='utf-8')
    # Reuse validated A/B/C reader without altering it. Third slot = original.
    compare = {'status':'ok', 'variants':{
        'balanced':{'wav':str(before)},'vocal-focus':{'wav':str(final_path)},
        'punchy':{'wav':str(before)}}}
    return {'report':str(report_path),'comparison':compare,'original':str(before),'after':str(final_path)}
