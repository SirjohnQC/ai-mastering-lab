"""Conservative album consistency advice from previously measured master metrics.

Read-only and intentionally *not* an automatic EQ or loudness controller.
Broad relative FFT band ratios can reflect arrangement, not a defect.
Never recommend exact plugin gains from sampled spectra.
"""
from __future__ import annotations

import math

BAND_LABELS = (
    ('graves', 'bass'),
    ('bas-médiums', 'low mids'),
    ('médiums', 'mids'),
    ('présence', 'presence'),
    ('aigus', 'highs'),
)
LEVEL_REVIEW_LUFS = 1.5
SPECTRAL_REVIEW_DB = 4.0
MAX_VALID_SPECTRAL_DIFFERENCE_DB = 36.0


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def advise_album(report: dict) -> dict:
    """Build non-destructive per-track review cards from a v0.25.0 audit."""
    if not isinstance(report, dict) or report.get('schema_version') != 1:
        raise ValueError('Album Intelligence report schema 1 required.')
    tracks = report.get('tracks')
    if not isinstance(tracks, list) or not tracks:
        raise ValueError('Missing album tracks.')
    ref_index = report.get('reference_index')
    if not isinstance(ref_index, int) or not 0 <= ref_index < len(tracks):
        raise ValueError('Invalid album reference.')
    cards = []
    for index, row in enumerate(tracks):
        status = row.get('status')
        card = {'index':index, 'title':str(row.get('title',''))[:150],
                'status':status, 'priority':'none', 'recommendations':[]}
        if status == 'reference':
            card['priority'] = 'reference'
            card['recommendations'].append({
                'kind':'reference','direction':'none',
                'detail':'Chosen album anchor; do not process automatically.'})
        elif status != 'measured':
            card['priority'] = 'not_ready'
            card['recommendations'].append({
                'kind':'unavailable','direction':'none',
                'detail':'Requires a valid completed QC-pass master.'})
        else:
            lufs_delta = row.get('lufs_delta')
            true_peak = row.get('true_peak_dbtp')
            bands = row.get('relative_band_delta_db')
            if (not _finite(lufs_delta) or not _finite(true_peak) or
                    not isinstance(bands, list) or len(bands) != len(BAND_LABELS) or
                    any(not _finite(v) for v in bands)):
                card['priority'] = 'not_ready'
                card['recommendations'].append({
                    'kind':'unavailable','direction':'none',
                    'detail':'Incomplete measured metrics; verify QC data.'})
            else:
                notes = card['recommendations']
                if true_peak > -1.0:
                    notes.append({'kind':'true_peak','direction':'review',
                                  'detail':'Measured true peak exceeds the -1 dBTP QC ceiling. Recheck the existing master.'})
                if abs(lufs_delta) > LEVEL_REVIEW_LUFS:
                    direction = 'quieter' if lufs_delta < 0 else 'louder'
                    notes.append({'kind':'loudness','direction':direction,
                                  'difference_lufs':round(lufs_delta,2),
                                  'detail':'Review perceived level relative to the reference. LUFS difference is not a recommended gain value.'})
                if any(abs(x) > MAX_VALID_SPECTRAL_DIFFERENCE_DB for x in bands):
                    notes.append({'kind':'spectrum_unreliable','direction':'review',
                                  'detail':'Extreme sampled band difference: likely sparse energy or different arrangement. Avoid automatic EQ.'})
                else:
                    # Pick one broad region, not five independent EQ commands.
                    strongest = max(range(len(bands)),key=lambda i:abs(bands[i]))
                    difference = bands[strongest]
                    if abs(difference) > SPECTRAL_REVIEW_DB:
                        fr,en = BAND_LABELS[strongest]
                        notes.append({'kind':'spectrum','direction':'higher' if difference > 0 else 'lower',
                                      'band_index':strongest,'band_fr':fr,'band_en':en,
                                      'relative_difference_db':round(difference,2),
                                      'detail':'Compare the overall tonal impression by ear. This spectral share is not a suggested EQ gain.'})
                card['priority'] = 'review' if notes else 'close'
                if not notes:
                    notes.append({'kind':'close','direction':'none',
                                  'detail':'Measured differences are within review thresholds; no adjustment suggested.'})
        cards.append(card)
    return {'schema_version':1,'reference_index':ref_index,
            'reference_title':str(report.get('reference_title',''))[:150],
            'tracks':cards,
            'limitations':'Non-destructive review only; no EQ parameters, no gain automation, no audio writes.'}


def localized_card(card: dict, language='fr') -> str:
    """Short actionable listening suggestions; no imaginary sound-quality grades."""
    en = language == 'en'
    parts = []
    for advice in card.get('recommendations', []):
        kind = advice.get('kind')
        if kind == 'reference':
            parts.append('Reference track — no adjustments' if en else 'Chanson de référence — aucun ajustement')
        elif kind == 'unavailable':
            parts.append('QC master required' if en else 'Master QC requis')
        elif kind == 'true_peak':
            parts.append('⚠ True Peak above −1 dBTP — review export' if en else '⚠ True Peak au-dessus de −1 dBTP — vérifier le master')
        elif kind == 'loudness':
            direction = advice['direction']
            if en:
                parts.append('Listen for lower perceived level' if direction=='quieter' else 'Listen for higher perceived level')
            else:
                parts.append('Écouter : niveau perçu possiblement plus faible' if direction=='quieter'
                             else 'Écouter : niveau perçu possiblement plus fort')
        elif kind == 'spectrum_unreliable':
            parts.append('Spectral comparison uncertain — do not EQ automatically'
                         if en else 'Écart spectral incertain — éviter toute EQ automatique')
        elif kind == 'spectrum':
            band = advice['band_en'] if en else advice['band_fr']
            high = advice['direction']=='higher'
            parts.append((f'Compare {band}: relatively ' + ('more' if high else 'less') + ' energy'
                          if en else f'Comparer les {band} : énergie relative ' + ('plus élevée' if high else 'plus faible')))
        elif kind == 'close':
            parts.append('No adjustment suggested' if en else 'Aucun ajustement suggéré')
    return ' · '.join(parts)
