"""Isolated Pro-C 3 parameter validation on GENERATED audio only.

It cannot render user songs and NEVER authorizes automatic compression.
Uses exact measured normalized calibration points; no interpolation or guessed units.
"""
from __future__ import annotations
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .pro_c3_multipoint import INDICES, _parse_physical
from .pro_c3_testbench import (build_probe, inspect_render_shape,
                                measure_response, _verified_plugin)

# Precise grid points the user's Pro-C 3 has returned through getText.
# Two intentionally contrasting compressor settings for a synthetic signal.
SCENARIOS = {
    'gentle': {'threshold': .85, 'ratio': .30, 'attack': .30, 'release': .30},
    'firm': {'threshold': .70, 'ratio': .70, 'attack': .30, 'release': .30},
}
AUTO_GAIN_INDEX = 19
# The only accepted texts for non-numeric controls, selected by read-back.


def _lookup_grid(report, role, normalized):
    if report.get('read_only') is not True or report.get('method') != 'getText':
        raise ValueError('Grille non authentifiée en lecture seule.')
    if report.get('display_mapping_status', {}).get(role) != 'text_grid_plausible':
        raise ValueError(f'Grille {role} non exploitable.')
    pts = report.get('probe_points', {}).get(role, [])
    matches = [p for p in pts if abs(float(p.get('normalized', -999)) - normalized) < 0.00001]
    if len(matches) != 1:
        raise ValueError(f'Point {role}={normalized} absent ou dupliqué.')
    p = matches[0]
    physical = p.get('physical')
    if isinstance(physical, bool) or not isinstance(physical, (float, int)) or not math.isfinite(physical):
        raise ValueError(f'Valeur physique {role} invalide.')
    if _parse_physical(role, p.get('display_text')) is None:
        raise ValueError(f'Unité non reconnue pour {role}.')
    return p


def prepare_scenario(grid, name):
    if name not in SCENARIOS:
        raise ValueError('Scénario inconnu.')
    values = SCENARIOS[name]
    expected = {role: _lookup_grid(grid, role, n) for role, n in values.items()}
    changes = [(INDICES[role], n) for role, n in values.items()]
    changes.append((AUTO_GAIN_INDEX, 0.0))
    return expected, changes


def validate_readback(result, expected):
    """Check actual plugin parameter echoes, including index/normalized/value.

    Absence of the echo is a failure, not permission to assume success.
    """
    raw = result.get('parameter_changes')
    if not isinstance(raw, list):
        raise ValueError('JUCE ne retourne pas les paramètres effectivement appliqués.')
    echoes = {}
    for item in raw:
        idx = item.get('index') if isinstance(item, dict) else None
        if idx in echoes:
            raise ValueError(f'Écho dupliqué à l’index {idx}.')
        echoes[idx] = item
    checked = {}
    for role, expected_point in expected.items():
        idx = INDICES[role]
        item = echoes.get(idx)
        if not item:
            raise ValueError(f'Aucun retour du plugin pour {role} (index {idx}).')
        text = str(item.get('text', item.get('display_text', ''))).strip()
        actual = _parse_physical(role, text)
        target = float(expected_point['physical'])
        # Text values may be rounded by the VST; allow UI rounding only.
        tolerance = {'threshold': .08, 'ratio': .06, 'attack': .15, 'release': 1.0}[role]
        if actual is None or not math.isfinite(actual) or abs(actual - target) > tolerance:
            raise ValueError(f'{role}: demandé {target}, FabFilter rapporte {text!r}.')
        # If JUCE echoes normalized setting, verify it as well.
        echoed_norm = item.get('normalized_value', item.get('normalized'))
        if echoed_norm is not None:
            if not isinstance(echoed_norm, (int, float)) or not math.isfinite(echoed_norm) or abs(echoed_norm - expected_point['normalized']) > .0002:
                raise ValueError(f'{role}: valeur normalisée relue différente.')
        checked[role] = {'index': idx, 'requested_normalized': expected_point['normalized'],
                         'expected_physical': target, 'plugin_text': text, 'actual_physical': actual}
    gain = echoes.get(AUTO_GAIN_INDEX)
    if not gain or str(gain.get('text', '')).strip().casefold() != 'off':
        raise ValueError('Pro-C 3 Auto Gain non confirmé Off.')
    return checked


def validate_dsp(gentle, firm):
    a, b = gentle['measurements'], firm['measurements']
    if not (a['nonzero_output'] and b['nonzero_output']):
        raise ValueError('Sortie audio vide.')
    if not all(math.isfinite(float(m['processed_sample_peak_dbfs'])) and m['processed_sample_peak_dbfs'] < 0 for m in (a, b)):
        raise ValueError('Crête non finie ou hors plage.')
    gap = float(b['high_level_attenuation_db']) - float(a['high_level_attenuation_db'])
    return {'high_level_attenuation_delta_db': round(gap, 3),
            'firm_more_compression_observed': bool(gap > 1.0),
            'note': 'Comparaison relative sur un sinus synthétique; pas de validation musicale.'}


def run_validation(root, *, host=None, plugin=None, runner=None):
    """Create two controlled renders in a diagnostic-only directory.

    No user audio input argument is accepted. Success never enables Auto Produce.
    """
    root = Path(root).resolve()
    host = Path(host or root / 'native/build/mastering-host_artefacts/Release/mastering-host.exe').resolve()
    plugin = Path(plugin or 'C:/Program Files/Common Files/VST3/FabFilter/FabFilter Pro-C 3.vst3').resolve()
    grid_path = root / 'settings/pro_c3_multipoint.json'
    if not host.is_file() or not plugin.exists() or plugin.suffix.lower() != '.vst3':
        raise FileNotFoundError('Host JUCE ou plugin Pro-C 3 introuvable.')
    grid = json.loads(grid_path.read_text(encoding='utf-8'))
    if runner is None:
        from .host import run_host
        runner = run_host
    inspection = runner(host, 'inspect', plugin=plugin, timeout=90)
    _verified_plugin(inspection)
    folder = root / 'settings/pro_c3_parameter_validation' / (datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    before = folder / 'synthetic-before.wav'
    report_path = folder / 'report.json'
    report = {'schema_version': 1, 'kind': 'pro_c3_parameter_validation',
              'created_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'failed', 'mapping_verified': False, 'ready_to_render': False,
              'automatic_compression_enabled': False, 'plugin': str(plugin), 'host': str(host),
              'scenarios': {}, 'note': 'Validation synthétique seulement; compression des chansons toujours verrouillée.'}
    try:
        build_probe(before)
        for name in SCENARIOS:
            expected, changes = prepare_scenario(grid, name)
            dest = folder / f'synthetic-{name}-pro-c3.wav'
            result = runner(host, 'render', plugin=plugin, input_file=before, output_file=dest,
                            parameter_changes=changes, timeout=180)
            checked = validate_readback(result, expected)
            declared_tail = int(result.get('tail_samples', 0) or 0)
            if declared_tail < 0 or declared_tail > 48000:
                raise ValueError('Queue audio JUCE absente/invalide ou excessive.')
            shape = inspect_render_shape(before, dest, declared_tail)
            metrics = measure_response(before, dest, declared_tail=declared_tail, shape_info=shape)
            if not metrics['nonzero_output']:
                raise ValueError('Rendu Pro-C 3 silencieux.')
            report['scenarios'][name] = {'parameters': checked, 'wav_shape': shape, 'measurements': metrics,
                                         'declared_tail_samples': declared_tail, 'output_path': str(dest)}
        report['comparison'] = validate_dsp(report['scenarios']['gentle'], report['scenarios']['firm'])
        # A plausible result means only the *test* worked, NOT that all mappings are verified.
        report['status'] = 'needs_review' if report['comparison']['firm_more_compression_observed'] else 'failed'
        if report['status'] == 'failed':
            report['warning'] = 'La compression plus forte n’a pas produit suffisamment de différence mesurée.'
        else:
            report['warning'] = 'Correspondances relues; validation incomplète hors de ces points synthétiques.'
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        tmp = report_path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(report_path)
    report['report_path'] = str(report_path)
    return report


def summarize(report):
    lines = ['Pro-C 3 — Validation des paramètres sur signal synthétique',
             'Statut : ' + report.get('status', 'inconnu'),
             'Compression automatique des chansons : VERROUILLÉE']
    for name, data in report.get('scenarios', {}).items():
        p = data.get('parameters', {})
        if p:
            lines.append(f"{name.title()} — " + ', '.join(f"{k}: {v['plugin_text']}" for k,v in p.items()))
        m = data.get('measurements', {})
        if m: lines.append(f"   atténuation forte : {m['high_level_attenuation_db']:+.2f} dB; faible : {m['low_level_attenuation_db']:+.2f} dB")
    if report.get('comparison'):
        lines.append('Différence d’atténuation (firm − gentle) : ' + str(report['comparison']['high_level_attenuation_delta_db']) + ' dB')
    if report.get('warning'): lines.append('Attention : ' + report['warning'])
    if report.get('error'): lines.append('Erreur : ' + report['error'])
    return '\n'.join(lines)
