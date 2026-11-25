"""Validate Auto Mix outputs for synchronized, non-destructive A/B/C playback."""
from __future__ import annotations
from pathlib import Path
import json

VARIANT_ORDER = ('balanced', 'vocal-focus', 'punchy')
VARIANT_LABELS = {'balanced': 'Balanced', 'vocal-focus': 'Vocal Focus', 'punchy': 'Punchy'}


def load_comparison(report: dict | Path | str):
    """Return ordered WAV paths, rejecting missing or incompatible input."""
    import soundfile as sf
    if isinstance(report, (Path, str)):
        report_path = Path(report).resolve()
        data = json.loads(report_path.read_text(encoding='utf-8'))
        base = report_path.parent
    else:
        data = report
        base = None
    if not isinstance(data, dict) or data.get('status') != 'ok':
        raise ValueError('Rapport Auto Mix invalide ou incomplet.')
    versions = data.get('variants')
    if not isinstance(versions, dict):
        raise ValueError('Aucune version Auto Mix disponible.')
    paths = {}
    reference = None
    for key in VARIANT_ORDER:
        item = versions.get(key)
        if not isinstance(item, dict) or not item.get('wav'):
            raise ValueError(f'Fichier absent pour {VARIANT_LABELS[key]}.')
        path = Path(item['wav']).expanduser()
        if not path.is_absolute() and base is not None:
            path = base / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f'WAV introuvable : {path}')
        info = sf.info(str(path))
        if info.frames <= 0 or info.samplerate <= 0 or info.channels != 2:
            raise ValueError(f'{VARIANT_LABELS[key]} : WAV stéréo valide requis.')
        spec = (info.samplerate, info.channels, info.frames)
        if reference is None:
            reference = spec
        elif spec != reference:
            raise ValueError(f'{VARIANT_LABELS[key]} : durée, fréquence ou canaux différents; comparaison synchronisée impossible.')
        paths[key] = path
    return paths, reference
