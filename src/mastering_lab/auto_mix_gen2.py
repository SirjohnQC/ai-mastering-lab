"""Opt-in Gen2 candidate mixer: bounded Ollama gain proposals, never an autonomous master.

Only a fixed five-group gain dictionary is accepted. No arbitrary commands, paths,
EQ parameters or plugin state changes are accepted from the language model.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import json
import math
import subprocess
import sys
import tempfile
import uuid

GROUPS = ('vocals', 'drums', 'bass', 'guitars', 'other')
LABELS = ('balanced', 'vocal-focus', 'punchy')
DEFAULT = {
    'balanced': dict.fromkeys(GROUPS, 0.0),
    'vocal-focus': {'vocals': 0.8, 'drums': -0.3, 'bass': -0.2, 'guitars': -0.4, 'other': -0.3},
    'punchy': {'vocals': 0.0, 'drums': 0.8, 'bass': 0.5, 'guitars': -0.3, 'other': -0.3},
}


def validate_deltas(raw: dict) -> dict:
    if not isinstance(raw, dict) or set(raw) != set(LABELS):
        raise ValueError('Hermes doit proposer exactement balanced, vocal-focus et punchy.')
    output = {}
    for name in LABELS:
        group_map = raw[name]
        if not isinstance(group_map, dict) or set(group_map) != set(GROUPS):
            raise ValueError(f'{name}: familles de stems incorrectes.')
        output[name] = {}
        for group in GROUPS:
            value = group_map[group]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'{name}/{group}: gain invalide.')
            if abs(value) > 1.0:
                raise ValueError(f'{name}/{group}: variation supérieure à ±1 dB.')
            output[name][group] = round(float(value), 2)
    if any(v != 0.0 for v in output['balanced'].values()):
        raise ValueError('Balanced doit préserver la configuration de départ.')
    return output


def model_proposal(evaluation: dict, *, model='hermes3:8b', timeout=90, transport=None) -> dict:
    """Request *only* bounded gain suggestions, not shell code or arbitrary plugin controls."""
    from .ai_review import _local_endpoint
    endpoint = _local_endpoint('http://127.0.0.1:11434')
    if not isinstance(model, str) or not model.strip() or len(model) > 120:
        raise ValueError('Nom du modèle invalide.')
    prompt = ('Tu ne peux pas écouter le son. Propose seulement des modifications de gain en dB pour '
              'trois variantes de prémix à comparer; pas de prédiction de qualité subjective. '
              'Réponds UNIQUEMENT avec le JSON {"deltas": {"balanced": {"vocals": 0, "drums": 0, '
              '"bass": 0, "guitars": 0, "other": 0}, "vocal-focus": {...}, "punchy": {...}}, '
              '"reason": "..."}. Chaque groupe doit être présent dans chaque variante. '
              'Balanced doit rester strictement à zéro. Toutes les valeurs doivent rester entre -1 et +1 dB. '
              'Les mesures ne prouvent pas qu’un mix sonne mieux.')
    payload = {'model': model, 'stream': False, 'format': 'json', 'options': {'temperature': 0.1},
               'messages': [{'role': 'system', 'content': prompt},
                            {'role': 'user', 'content': json.dumps(evaluation, ensure_ascii=False)}]}
    if transport is None:
        def transport(url, body, seconds):
            req = Request(url, data=json.dumps(body).encode('utf-8'),
                          headers={'Content-Type': 'application/json'}, method='POST')
            with urlopen(req, timeout=seconds) as response:
                return json.loads(response.read(400000).decode('utf-8'))
    content = transport(endpoint, payload, timeout)['message']['content']
    answer = json.loads(content) if isinstance(content, str) else content
    if not isinstance(answer, dict):
        raise ValueError('Réponse Hermes non structurée.')
    return {'deltas': validate_deltas(answer.get('deltas')), 'reason': str(answer.get('reason', ''))[:600],
            'model': model, 'source': 'hermes'}


def deterministic_proposal() -> dict:
    return {'deltas': validate_deltas(deepcopy(DEFAULT)), 'reason':
            'Hermes indisponible ou non sollicité : trois variations de gain conservatrices et déterministes.',
            'model': None, 'source': 'fallback'}


def build_configs(config: dict, deltas: dict) -> dict:
    from .auto_mix_candidates import _group
    changes = validate_deltas(deltas)
    tracks = config.get('tracks')
    if not isinstance(tracks, list) or not tracks:
        raise ValueError('Aucun stem configuré.')
    output = {}
    for name in LABELS:
        candidate = deepcopy(config)
        for track in candidate['tracks']:
            current = float(track.get('gain_db', 0))
            if not math.isfinite(current) or not -18 <= current <= 18:
                raise ValueError('Gain de piste hors limites.')
            if not track.get('mute', False):
                current = max(-18., min(18., current + changes[name][_group(track)]))
            track['gain_db'] = round(current, 2)
        candidate['auto_mix_variant'] = f'gen2-{name}'
        output[name] = candidate
    return output


def read_session(report_path: str | Path):
    path = Path(report_path).resolve()
    report = json.loads(path.read_text(encoding='utf-8'))
    if report.get('status') != 'ok':
        raise ValueError('Session Auto Mix non valide.')
    source = report.get('source') or {}
    if not all(source.get(k) for k in ('config', 'folder', 'prepared')):
        raise ValueError('Cette session est antérieure à v0.10.9. Regénère une fois Auto Mix pour activer Gen 2.')
    cfg = Path(source['config']).resolve()
    folder = Path(source['folder']).resolve()
    prepared = Path(source['prepared']).resolve()
    if not cfg.is_file() or not folder.is_dir():
        raise FileNotFoundError('Projet initial introuvable : recharge les stems puis refais Auto Mix.')
    return report, cfg, folder, prepared


def render_generation(report_path: str | Path, proposal: dict, *, project_root: str | Path | None = None,
                      runner=subprocess.run) -> dict:
    """Only render after explicit UI approval; create new session and never overwrite."""
    report, config_path, folder, prepared = read_session(report_path)
    config = json.loads(config_path.read_text(encoding='utf-8'))
    configs = build_configs(config, proposal['deltas'])
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
    engine = root / 'scripts' / 'stem_mix.py'
    if not engine.is_file():
        raise FileNotFoundError(f'Moteur de rendu introuvable : {engine}')
    parent = Path(report_path).resolve().parent / 'generations'
    parent.mkdir(parents=True, exist_ok=True)
    generation = parent / ('gen2-' + uuid.uuid4().hex[:10])
    generation.mkdir()
    variants = {}
    try:
        with tempfile.TemporaryDirectory(prefix='aml-gen2-') as temp:
            for name in LABELS:
                candidate_config = Path(temp) / f'{name}.json'
                candidate_config.write_text(json.dumps(configs[name], ensure_ascii=False, indent=2), encoding='utf-8')
                wav_path = generation / f'{name}.wav'
                cmd = [sys.executable, str(engine), '--folder', str(folder), '--config', str(candidate_config),
                       '--prepared', str(prepared), '--output', str(wav_path)]
                result = runner(cmd, cwd=str(root), capture_output=True, text=True, timeout=900)
                if result.returncode or not wav_path.is_file():
                    detail = (result.stderr + '\n' + result.stdout).strip()[-1400:]
                    raise RuntimeError(f'{name}: {detail or "Rendu WAV impossible"}')
                variants[name] = {'wav': str(wav_path.resolve())}
        from .mix_comparison import load_comparison
        response = {'status': 'ok', 'variants': variants,
                    'source': {'config': str(config_path), 'folder': str(folder), 'prepared': str(prepared)},
                    'parent_comparison': str(Path(report_path).resolve()),
                    'generation': 2, 'proposal': proposal,
                    'created_utc': datetime.now(timezone.utc).isoformat(),
                    'warning': 'Prémix non masterisés. Hermes ne reçoit pas le son et ne juge pas la qualité à l’oreille.'}
        load_comparison(response)  # Validate all 3 WAVs are synchronized before exposing the session.
        (generation / 'comparison.json').write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'folder': str(generation), 'comparison': str(generation / 'comparison.json')}
    except Exception:
        (generation / 'FAILED.txt').write_text('Rendu inachevé : aucune comparaison validée.', encoding='utf-8')
        raise
