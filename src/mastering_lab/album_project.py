"""Persistent, conservative album inventory and QC summaries.

No mixing is performed here. Stereo WAVs can be sent to existing technical Auto
Master. Stem folders are listed but NEVER treated as finished stereo masters.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone

SCHEMA = 1


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _track(path, kind):
    path = Path(path).resolve()
    if kind not in ('stereo', 'stems'):
        raise ValueError('Type de piste invalide')
    if kind == 'stereo' and not (path.is_file() and path.suffix.lower() == '.wav'):
        raise ValueError('Auto Master album exige un WAV stéréo existant')
    if kind == 'stems' and not (path.is_dir() and len(list(path.glob('*.wav'))) >= 2):
        raise ValueError('Un dossier stems doit contenir au moins deux WAV')
    return {'path': str(path), 'kind': kind, 'title': path.stem if kind == 'stereo' else path.name,
            'status': 'waiting', 'result': None, 'error': ''}


def empty_project():
    return {'schema': SCHEMA, 'album': 'Mon album', 'created': _now(), 'tracks': []}


def load_project(path):
    path = Path(path)
    if not path.exists():
        return empty_project()
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or not isinstance(data.get('tracks'), list):
        raise ValueError('Projet album incompatible ou invalide')
    seen = set()
    for row in data['tracks']:
        if not isinstance(row, dict) or row.get('kind') not in ('stereo','stems') or not row.get('path'):
            raise ValueError('Entrée album invalide')
        identifier = str(Path(row['path']).resolve()).casefold()
        if identifier in seen:
            raise ValueError('Piste album en double')
        seen.add(identifier)
    return data


def save_project(path, project):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def add_entries(project, paths, kind):
    known = {str(Path(t['path']).resolve()).casefold() for t in project['tracks']}
    added = 0
    for path in paths:
        row = _track(path, kind)
        key = row['path'].casefold()
        if key not in known:
            project['tracks'].append(row)
            known.add(key)
            added += 1
    return added


def discover_album(folder):
    """Only unambiguous 1-level structures; no recursive directory guessing."""
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError('Dossier album introuvable')
    songs = [(str(x), 'stereo') for x in sorted(folder.glob('*.wav'))]
    for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
        stem_dir = next((p for p in (sub/'stems', sub/'stem') if p.is_dir()), None)
        if stem_dir and len(list(stem_dir.glob('*.wav'))) >= 2:
            songs.append((str(stem_dir), 'stems'))
            continue
        wavs = sorted(sub.glob('*.wav'))
        if len(wavs) == 1:
            songs.append((str(wavs[0]), 'stereo'))
        elif len(wavs) > 1:
            songs.append((str(sub), 'stems'))
    return songs


def album_summary(project):
    entries = []
    for idx, row in enumerate(project['tracks'], start=1):
        result = row.get('result') or {}
        entries.append({'track_number': idx, 'title': row['title'], 'kind': row['kind'],
                        'source': row['path'], 'status': row.get('status', 'waiting'),
                        'master': result.get('file'), 'lufs': result.get('output_lufs'),
                        'true_peak_dbtp': result.get('output_true_peak_dbtp'),
                        'qc_issues': result.get('qc_issues', []), 'error': row.get('error',''),
                        'candidates': result.get('album_candidates', {}),
                        'selected_candidate': result.get('album_selected_candidate'),
                        'pipeline': result.get('album_pipeline')})
    passes = [e for e in entries if e['status']=='qc_pass' and isinstance(e['lufs'], (int,float))]
    spread = round(max(e['lufs'] for e in passes) - min(e['lufs'] for e in passes), 2) if len(passes)>=2 else None
    return {'album': project.get('album','Mon album'), 'created_at': _now(),
            'tracks': entries, 'qc_pass_count': len(passes), 'total_tracks': len(entries),
            'integrated_lufs_range_db': spread,
            'warning': 'Comparaison technique seulement. La cohérence artistique et les masters de stems non traités exigent une validation.'}
