"""Read-only Pro-C 3 multi-point text lookup using a specifically upgraded JUCE host.

The 'probe' command MUST use AudioProcessorParameter::getText(value, maxLen)
and MUST NEVER call setValue, render, or processBlock. No readiness to render.
"""
from __future__ import annotations
import json
import math
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

INDICES = {'threshold': 1, 'ratio': 4, 'attack': 7, 'release': 8}
GRIDS = (0.05, 0.15, 0.30, 0.50, 0.70, 0.85, 0.95)
EXPECTED = {'threshold': 'Threshold', 'ratio': 'Ratio', 'attack': 'Attack', 'release': 'Release'}


def _parse_physical(role, text):
    s = str(text or '').strip().replace(',', '.')
    if role == 'threshold':
        m = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)\s*dB', s, re.I)
        return float(m.group(1)) if m else None
    if role == 'ratio':
        m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*:\s*1', s)
        return float(m.group(1)) if m else None
    m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(ms|msec|milliseconds?|s|sec|secs|seconds?)', s, re.I)
    return float(m.group(1)) * (1000 if m.group(2).lower() in {'s', 'sec', 'secs', 'second', 'seconds'} else 1) if m else None


def validate_probes(raw, baseline=None):
    """Validate exact plugin/role/index and monotonically ordered display evidence."""
    if not isinstance(raw, dict) or 'pro-c 3' not in str(raw.get('name', '')).casefold():
        raise ValueError('Réponse multipoint : plugin Pro-C 3 non confirmé.')
    if raw.get('read_only') is not True or raw.get('method') != 'getText':
        raise ValueError('La commande native ne garantit pas le mode lecture seule.')
    points = raw.get('probe_points')
    if not isinstance(points, list):
        raise ValueError('La commande probe n’est pas prise en charge par ce mastering-host.exe. Reconstruis le moteur JUCE.')
    groups = {}
    for item in points:
        if not isinstance(item, dict):
            raise ValueError('Point de calibration malformé.')
        idx = item.get('index')
        role = next((r for r, i in INDICES.items() if i == idx), None)
        if role is None or item.get('name') != EXPECTED[role]:
            raise ValueError('Index ou nom de paramètre inattendu : calibration refusée.')
        n = item.get('normalized')
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not 0 <= n <= 1:
            raise ValueError('Point normalisé invalide.')
        text = str(item.get('display_text', ''))[:100]
        physical = _parse_physical(role, text)
        groups.setdefault(role, []).append({'normalized': float(n), 'display_text': text, 'physical': physical})
    findings = {}
    for role in INDICES:
        ps = sorted(groups.get(role, []), key=lambda x: x['normalized'])
        actual = {round(p['normalized'], 5) for p in ps}
        if not all(round(n, 5) in actual for n in GRIDS):
            findings[role] = 'insufficient_points'
        elif any(p['physical'] is None or not math.isfinite(p['physical']) for p in ps):
            findings[role] = 'unparsed_units'
        else:
            vals = [p['physical'] for p in ps]
            # Nondecreasing or nonincreasing; NOT proof of accuracy of plugin behavior.
            if not (all(a <= b for a, b in zip(vals, vals[1:])) or all(a >= b for a, b in zip(vals, vals[1:]))):
                findings[role] = 'non_monotonic'
            else:
                findings[role] = 'text_grid_plausible'
        groups[role] = ps
    # Baseline inspections may have different plugin versions/index mappings.
    if baseline:
        for role, idx in INDICES.items():
            entries = (baseline.get('candidates') or {}).get(role) or []
            if len(entries) != 1 or entries[0].get('index') != idx:
                raise ValueError('La calibration précédente ne correspond pas aux indices attendus.')
    return {
        'schema_version': 4, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
        'plugin': raw['name'], 'method': 'getText', 'read_only': True,
        'probe_points': groups, 'display_mapping_status': findings,
        'mapping_verified': False, 'ready_to_render': False,
        'note': 'Grille getText lue sans setValue. Conversion numérique et réaction DSP non validées; compression verrouillée.'
    }


def probe_and_save(root, *, host=None, plugin=None, runner=None):
    from .pro_c3_calibration import read_calibration_report
    root = Path(root).resolve()
    baseline = read_calibration_report(root)
    host = Path(host or root / 'native/build/mastering-host_artefacts/Release/mastering-host.exe')
    plugin = Path(plugin or 'C:/Program Files/Common Files/VST3/FabFilter/FabFilter Pro-C 3.vst3')
    if not host.is_file() or not plugin.exists() or plugin.suffix.lower() != '.vst3':
        raise FileNotFoundError('Moteur JUCE ou plugin Pro-C 3 introuvable; aucun fichier audio modifié.')
    if runner is None:
        def runner(h, p):
            result = subprocess.run([str(h), 'probe', '--plugin', str(p)], capture_output=True, text=True, timeout=90)
            try:
                payload = json.loads(result.stdout)
            except (ValueError, TypeError):
                raise RuntimeError('Le moteur JUCE ne reconnaît pas encore probe. Applique le patch natif et reconstruis-le.')
            if result.returncode or 'error' in payload:
                raise RuntimeError(f"Sondage JUCE : {payload.get('error', 'échec')} (code {result.returncode})")
            return payload
    report = validate_probes(runner(host, plugin), baseline=baseline)
    path = root / 'settings/pro_c3_multipoint.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    try:
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    report['report_path'] = str(path)
    return report


def summarize(report):
    lines = ['Pro-C 3 — grille multipoint (lecture seule)', 'Compression : BLOQUÉE — pas de rendu audio']
    for role in INDICES:
        lines.append(f"\n{role.title()} : {report.get('display_mapping_status', {}).get(role, 'inconnu')}")
        for point in report.get('probe_points', {}).get(role, []):
            lines.append(f"  {point['normalized']:.3f} → {point['display_text']}")
    lines.append('\nLes textes seuls ne constituent pas une validation de la réponse DSP.')
    return '\n'.join(lines)
