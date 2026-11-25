"""Explain why a Gentle Pro-C 3 preview can sound almost unchanged.

Evidence-based, deliberately non-diagnostic: a global peak and the plugin's
displayed threshold do NOT disclose its detector gain-reduction history.
No audio writes, model inference or automatic approval.
"""
from __future__ import annotations

import math
import re


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _threshold_from_report(report, variant):
    """Use actual JUCE readback text, never treat normalized knob units as dB."""
    params = (report.get('scenarios') or {}).get(variant, {}).get('parameters', {})
    threshold = params.get('threshold', {})
    actual = threshold.get('actual_physical')
    if _number(actual):
        return float(actual)
    display = threshold.get('plugin_text', '')
    match = re.fullmatch(r'\s*([+-]?\d+(?:\.\d+)?)\s*dB\s*', str(display), re.I)
    return float(match.group(1)) if match else None


def explain_gentle(metrics, mix, report=None):
    """Return a cautious concise explanation and evidence for one mix.

    This only evaluates two already-rendered WAVs and stored readback.
    Returns 'unknown' rather than claiming that a song is compressed.
    """
    original = metrics.get(mix + '/original', {})
    gentle = metrics.get(mix + '/gentle', {})
    if not isinstance(original, dict) or not isinstance(gentle, dict):
        return {'status':'unavailable', 'reason':'Mesures WAV absentes.'}
    required = ('rms_dbfs', 'sample_peak_dbfs', 'crest_db')
    if not all(_number(original.get(k)) for k in required):
        return {'status':'unavailable', 'reason':'Mesures de la source incomplètes.'}
    threshold = _threshold_from_report(report or {}, 'gentle')
    window = gentle.get('window_analysis', {})
    if not isinstance(window, dict):
        window = {}
    evidence = {'source_peak_dbfs':round(float(original['sample_peak_dbfs']),2),
                'source_crest_db':round(float(original['crest_db']),2),
                'threshold_readback_db':round(threshold,2) if threshold is not None else None,
                'loud_window_relative_db':window.get('loud_relative_to_quiet_db')}
    if gentle.get('same_samples_as_original') is True:
        return {'status':'identical',
                'reason':'Gentle et Original ont des échantillons identiques. Vérifier le rendu, le bypass et le routage Pro-C 3.',
                'evidence':evidence}
    if not _number(gentle.get('rms_delta_db')):
        return {'status':'unavailable', 'reason':'Comparaison audio Gentle incomplète.', 'evidence':evidence}
    rms_delta = float(gentle['rms_delta_db'])
    weak_window = (window.get('status') == 'measured' and
                   bool(window.get('effect_nearly_inaudible_warning')))
    weak_global = abs(rms_delta) < 0.15
    if not weak_window or not weak_global:
        return {'status':'measurable',
                'reason':'Gentle modifie le WAV. La différence peut être discrète à l’oreille et varier selon le passage.',
                'evidence':evidence}
    if threshold is not None and original['sample_peak_dbfs'] < threshold - 1.0:
        return {'status':'probably_below_threshold',
                'reason':'La crête mesurée reste sous le seuil relu de Pro-C 3. Ce réglage risque de déclencher très peu de compression.',
                'evidence':evidence}
    if original['crest_db'] <= 9:
        return {'status':'dense_input_possible',
                'reason':'Le mix a peu d’écart entre crête et niveau moyen, mais cela ne prouve PAS qu’il soit déjà compressé. Gentle a un effet très faible.',
                'evidence':evidence}
    return {'status':'subtle_unresolved',
            'reason':'Gentle a très peu d’effet mesuré, mais le mix n’est pas manifestement écrasé. Seuil, enveloppe d’attaque et contenu musical peuvent expliquer le résultat.',
            'evidence':evidence}
