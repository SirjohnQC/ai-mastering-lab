"""Non-destructive time-ranged repair annotations for audio projects.

This module makes NO claim to detect AI-generated content or audible defects.
Markers are human supplied. Stored in JSON and exportable as CSV for DAWs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import os
import re
import tempfile

ACTIONS = ('review', 'regenerate', 'replace_vocal', 'overdub_vocal', 'overdub_guitar', 'repair_mix', 'leave')
ISSUES = ('metallic_voice', 'sibilance', 'digital_artifact', 'cymbal_texture', 'guitar_noise', 'timing', 'other')


def project_id(source: Path) -> str:
    """Stable for a file path; avoids collisions between equally named tracks."""
    clean = re.sub(r'[^A-Za-z0-9_-]+', '-', source.stem).strip('-')[:48] or 'song'
    digest = hashlib.sha256(str(source.resolve()).casefold().encode('utf-8')).hexdigest()[:10]
    return f'{clean}-{digest}'


def markers_path(root: Path, source: Path) -> Path:
    return root / 'sound' / 'output' / 'repairs' / project_id(source) / 'markers.json'


def format_time(ms: int) -> str:
    seconds = max(0, int(ms)) // 1000
    return f'{seconds // 60:02d}:{seconds % 60:02d}.{max(0,int(ms)) % 1000:03d}'


def validate_marker(marker: dict, duration_ms: int | None = None) -> dict:
    start = int(marker['start_ms']); end = int(marker['end_ms'])
    if start < 0 or end <= start:
        raise ValueError('Marker end must be later than start, with non-negative times')
    if duration_ms is not None and duration_ms > 0 and end > duration_ms:
        raise ValueError('Marker extends past the track duration')
    issue = str(marker['issue']); action = str(marker['action'])
    if issue not in ISSUES or action not in ACTIONS:
        raise ValueError('Unknown issue/action')
    notes = str(marker.get('notes', ''))[:2000]
    take = str(marker.get('take_path', ''))[:1024]
    return {'start_ms': start, 'end_ms': end, 'issue': issue, 'action': action,
            'notes': notes, 'take_path': take,
            'created_utc': str(marker.get('created_utc') or datetime.now(timezone.utc).isoformat())}


def read_markers(root: Path, source: Path) -> list[dict]:
    path = markers_path(root, source)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('source') != str(source.resolve()):
        raise ValueError('Marker file belongs to a different audio source')
    rows = data.get('markers', [])
    if not isinstance(rows, list):
        raise ValueError('Invalid marker list')
    return sorted((validate_marker(m) for m in rows), key=lambda x: (x['start_ms'], x['end_ms']))


def write_markers(root: Path, source: Path, markers: list[dict], duration_ms: int | None = None) -> Path:
    items = sorted((validate_marker(m, duration_ms) for m in markers), key=lambda x: (x['start_ms'], x['end_ms']))
    path = markers_path(root, source); path.parent.mkdir(parents=True, exist_ok=True)
    data = {'schema_version': 1, 'source': str(source.resolve()), 'markers': items}
    # atomic replacement: a crash should not destroy prior annotations
    fd, tmp = tempfile.mkstemp(prefix='.markers-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(data, out, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def export_csv(root: Path, source: Path) -> Path:
    path = markers_path(root, source).with_name('markers.csv')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as out:
        writer = csv.writer(out)
        writer.writerow(('Start', 'End', 'Issue', 'Suggested action', 'Notes', 'Replacement recording'))
        for m in read_markers(root, source):
            writer.writerow((format_time(m['start_ms']), format_time(m['end_ms']), m['issue'],
                             m['action'], m['notes'], m['take_path']))
    return path
