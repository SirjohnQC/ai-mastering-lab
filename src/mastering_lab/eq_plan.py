"""Read-only, bounded EQ audition suggestions from mix-wide DSP evidence.

No plugin state changes, no invented VST parameter IDs. Spectral shares are
broad descriptors, NOT proof of narrow resonances or instrument problems.
"""
from __future__ import annotations
import json
import math
from urllib.request import Request, urlopen

BANDS = {
    'sub_bass_20_120': (20, 120),
    'low_mid_120_500': (120, 500),
    'mid_500_5000': (500, 5000),
    'high_5000_20000': (5000, 20000),
}
MAX_MOVES = 3


def validate_plan(raw, evaluation):
    if not isinstance(raw, dict):
        raise ValueError('Réponse EQ: objet JSON requis.')
    moves = raw.get('moves')
    if not isinstance(moves, list) or len(moves) > MAX_MOVES:
        raise ValueError('EQ: zéro à trois suggestions seulement.')
    baseline = evaluation.get('metrics', {}).get('balanced', {})
    shares = baseline.get('spectral_shares', {})
    checked = []
    for i, move in enumerate(moves):
        if not isinstance(move, dict):
            raise ValueError(f'Proposition {i+1}: objet requis.')
        if move.get('target') != 'balanced_premix':
            raise ValueError('Seul le prémix Balanced est mesuré ici; aucune piste ne peut être ciblée.')
        band = move.get('evidence_band')
        if band not in BANDS or band not in shares:
            raise ValueError('Bande de preuve absente des mesures DSP.')
        freq, gain = move.get('frequency_hz'), move.get('gain_db')
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in (freq, gain)):
            raise ValueError('Fréquence ou gain non numérique.')
        lo, hi = BANDS[band]
        if not (lo <= freq <= hi) or not (-1.5 <= gain <= 1.5):
            raise ValueError('Fréquence hors de sa bande ou gain dépassant ±1,5 dB.')
        if abs(gain) < 0.1:
            raise ValueError('Gain trop faible pour une proposition utile.')
        reason = move.get('reason', '')
        if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 240:
            raise ValueError('Justification trop courte ou absente.')
        checked.append({'target':'balanced_premix','evidence_band':band,
                        'frequency_hz':round(float(freq),1),'gain_db':round(float(gain),2),
                        'spectral_share_pct':round(float(shares[band])*100,2),
                        'reason':reason.strip()})
    return {'moves':checked, 'status':'suggestions_only',
            'notice':'Hypothèses à écouter. Le DSP n’a pas confirmé une résonance précise; aucun VST modifié.'}


def propose_eq_plan(evaluation, *, model='hermes3:8b', requester=None, timeout=90):
    if evaluation.get('status') != 'ok' or 'balanced' not in evaluation.get('metrics', {}):
        raise ValueError('Mesures DSP manquantes.')
    shares = evaluation['metrics']['balanced'].get('spectral_shares')
    if not isinstance(shares, dict) or any(k not in shares for k in BANDS):
        raise ValueError('Énergie fréquentielle indisponible.')
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= 120:
        raise ValueError('Modèle Ollama invalide.')
    system = ('Tu ne peux NI écouter la chanson NI identifier les défauts individuels des stems. '
              'Ces pourcentages spectraux décrivent le prémix, sans prouver de résonances. '
              'Propose de 0 à 3 petits essais EQ pour le prémix Balanced; zéro est permis et préférable '
              'si les mesures sont insuffisantes. Ne dis jamais que la qualité est prouvée. '
              'Retourne uniquement un objet JSON {"moves":[{"target":"balanced_premix",'
              '"evidence_band":"low_mid_120_500","frequency_hz":300,"gain_db":-0.5,'
              '"reason":"Essai prudent à valider à l’écoute"}]}. '
              'Bandes autorisées: sub_bass_20_120, low_mid_120_500, mid_500_5000, high_5000_20000. '
              'Chaque fréquence doit appartenir à sa bande et chaque gain entre -1.5 et +1.5 dB.')
    body = {'model':model,'stream':False,'think':False,'format':'json',
            'options':{'temperature':0,'num_predict':1400},
            'messages':[{'role':'system','content':system},
                        {'role':'user','content':json.dumps({'balanced_spectral_shares':shares}, ensure_ascii=False)}]}
    if requester is None:
        def requester(payload):
            req = Request('http://127.0.0.1:11434/api/chat', method='POST',
                          data=json.dumps(payload).encode('utf-8'),
                          headers={'Content-Type':'application/json'})
            with urlopen(req, timeout=timeout) as res:
                return json.loads(res.read(300000).decode('utf-8'))
    response = requester(body)
    if not isinstance(response, dict) or response.get('done_reason') == 'length':
        raise ValueError('Hermes a épuisé sa limite de tokens sans terminer sa proposition.')
    content = response.get('message', {}).get('content', '')
    if not isinstance(content, str) or not content.strip():
        raise ValueError('Hermes a retourné une proposition EQ vide.')
    result = validate_plan(json.loads(content), evaluation)
    result.update(model=model, source='Hermes', evidence_scope='whole_premix')
    return result


def format_plan(plan):
    lines = ['PRO-Q 4 — PROPOSITIONS À ÉCOUTER (NON APPLIQUÉES)',
             plan['notice'], 'Cible: prémix Balanced entier, pas les stems individuels.', '']
    if not plan['moves']:
        lines.append('Aucune correction recommandée avec ces mesures.')
    for index, move in enumerate(plan['moves'], 1):
        lines.append(f"{index}. {move['frequency_hz']:g} Hz · {move['gain_db']:+.2f} dB · "
                     f"{move['evidence_band']} ({move['spectral_share_pct']} % du spectre mesuré)")
        lines.append(f"   Essai: {move['reason']}")
    lines.append('\nAucun réglage VST, WAV ou projet n’a été modifié.')
    return '\n'.join(lines)
