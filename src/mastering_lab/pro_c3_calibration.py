"""Read-only JUCE Pro-C 3 inspection and calibration evidence gathering.

Never set plugin values or render audio. Text displayed by VST is NOT a
verified normalized->physical-unit conversion.
"""
from __future__ import annotations
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

TARGETS = {
    'threshold': ('threshold', 'seuil'),
    'ratio': ('ratio', 'rapport'),
    'attack': ('attack', 'attaque'),
    'release': ('release', 'relachement', 'relâchement'),
    'knee': ('knee', 'coude'),
    'makeup': ('makeup', 'make-up', 'output gain', 'output level'),
}
REQUIRED = ('threshold', 'ratio', 'attack', 'release')


def _tokens(value):
    return re.sub(r'\s+', ' ', str(value or '').casefold().strip())


def _normalized(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and 0 <= value <= 1 else None


def _display(value):
    if not isinstance(value, str):
        return ''
    return ' '.join(value.strip().split())[:100]


def discover_mapping(parameters):
    """Find candidates and preserve current plugin-displayed values."""
    if not isinstance(parameters, list):
        raise ValueError('Inspection JUCE : liste de paramètres absente.')
    candidates = {}
    for i, item in enumerate(parameters):
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or item.get('label') or '').strip()
        searchable = _tokens(name)
        if not name or len(name) > 128 or item.get('automatable') is False:
            continue
        index = item.get('index', i)
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            continue
        for role, aliases in TARGETS.items():
            if any(searchable == a or searchable.startswith(a + ' (') for a in aliases):
                candidates.setdefault(role, []).append({
                    'index': index, 'name': name,
                    'normalized_value': _normalized(item.get('value')),
                    'display_text': _display(item.get('text')),
                })
    status = {role: 'candidate_only' if len(candidates.get(role, [])) == 1 else
              ('ambiguous' if candidates.get(role) else 'missing') for role in REQUIRED}
    return {'candidates': candidates, 'required_status': status,
            'mapping_verified': False, 'ready_to_render': False}


def displayed_value_evidence(report):
    """Report whether JUCE returned plausible units (not a mapping proof)."""
    candidates = report.get('candidates') or {}
    patterns = {
        'threshold': r'(?:^|\s)[+-]?\d+(?:[.,]\d+)?\s*dB\b',
        'ratio': r'\d+(?:[.,]\d+)?\s*:\s*1\b',
        'attack': r'\d+(?:[.,]\d+)?\s*(?:ms|s)\b',
        'release': r'\d+(?:[.,]\d+)?\s*(?:ms|s)\b',
    }
    result = {}
    for role in REQUIRED:
        entries = candidates.get(role, [])
        if len(entries) != 1:
            result[role] = 'unavailable'
            continue
        value = entries[0].get('display_text') or ''
        result[role] = 'displayed_unit_detected' if re.search(patterns[role], value, re.I) else 'requires_manual_review'
    return result


def calibration_summary(report):
    if not isinstance(report, dict):
        raise ValueError('Rapport Pro-C 3 invalide.')
    status, candidates = report.get('required_status') or {}, report.get('candidates') or {}
    lines = [
        'FabFilter Pro-C 3 — Calibration Lab (lecture seule)',
        f"Plugin : {report.get('plugin', 'Inconnu')}",
        f"Paramètres trouvés : {report.get('parameter_count', '?')}",
        'État : NON CALIBRÉ — rendu de compression BLOQUÉ', '',
    ]
    units = displayed_value_evidence(report)
    for role in REQUIRED:
        lines.append(f'{role.title()} : {status.get(role, "missing")} / {units[role]}')
        for candidate in (candidates.get(role) or [])[:10]:
            lines.append('    index={index} · {name} · normalisé={value} · affichage VST={text}'.format(
                index=candidate.get('index'), name=candidate.get('name'),
                value=candidate.get('normalized_value'), text=candidate.get('display_text') or '(non disponible)'))
    lines.extend([
        '', 'Les valeurs affichées sont un SEUL point par paramètre.',
        'Elles ne prouvent pas la conversion des valeurs normalisées.',
        'Prochaine étape : plusieurs points de contrôle et rendu sur signal de test.',
        'Aucun paramètre VST modifié, aucun WAV rendu.',
    ])
    return '\n'.join(lines)


def read_calibration_report(root):
    path = Path(root) / 'settings' / 'pro_c3_calibration.json'
    if not path.is_file():
        raise FileNotFoundError('Aucune calibration Pro-C 3 trouvée. Lance d’abord « Calibrer Pro-C 3 ».')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') not in (1, 2, 3):
        raise ValueError('Version de rapport Pro-C 3 non reconnue.')
    return data


def inspect_and_save(root, *, host=None, plugin=None, runner=None, report_path=None):
    """Read-only JUCE inspection; save parameter text in an atomic JSON report."""
    from .pro_c3_diagnostics import inspect_pro_c3
    root = Path(root).resolve()
    if runner is None:
        from .host import run_host
        runner = run_host
    recorded = []

    def capture(h, command, **kwargs):
        if command != 'inspect' or kwargs.get('parameter_changes') or kwargs.get('input_file'):
            raise RuntimeError('Calibration Lab : seule la commande inspect est autorisée.')
        result = runner(h, command, **kwargs)
        recorded.append(result)
        return result

    summary = inspect_pro_c3(root, host=host, plugin=plugin, runner=capture)
    if len(recorded) != 1:
        raise RuntimeError('Inspection JUCE inattendue.')
    parameters = recorded[0].get('parameters', [])
    mapping = discover_mapping(parameters)
    evidence = displayed_value_evidence(mapping)
    result = {
        'schema_version': 3,
        'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
        'plugin': summary['plugin'],
        'parameter_count': summary['parameters_count'],
        'parameter_metadata': [
            {'index': p.get('index', i),
             'name': str(p.get('name') or p.get('label') or '')[:128],
             'automatable': p.get('automatable'),
             'normalized_value': _normalized(p.get('value')),
             'display_text': _display(p.get('text'))}
            for i, p in enumerate(parameters) if isinstance(p, dict)
        ][:2048],
        'automatable_count': summary['automatable_count'],
        **mapping,
        'displayed_units': evidence,
        'note': 'Valeurs affichées par le VST au point courant. Conversion NON vérifiée; compression verrouillée.',
    }
    destination = Path(report_path) if report_path else root / 'settings' / 'pro_c3_calibration.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + '.tmp')
    try:
        with temp.open('w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    result['report_path'] = str(destination)
    return result
