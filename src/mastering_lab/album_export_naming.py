"""Album-only naming for mastered files. Original sources and premixes are untouched."""
from __future__ import annotations

import json
import re
from pathlib import Path


def song_name(folder: str | Path) -> str:
    """A folder literally named stem/stems belongs to its parent song directory."""
    path = Path(folder)
    return path.parent.name if path.name.casefold() in {'stem', 'stems'} else path.name


def safe_slug(title: str) -> str:
    """Readable, portable export prefix; avoids Windows-reserved path characters."""
    import unicodedata
    chars = unicodedata.normalize('NFKD', title)
    chars = ''.join(c for c in chars if not unicodedata.combining(c))
    chars = re.sub(r'[^A-Za-z0-9]+', '-', chars).strip('-').lower()
    return (chars[:90].rstrip('-') or 'untitled')


def rename_album_master(result: dict, title: str, variant: str | None = None) -> dict:
    """Rename generated master and QC sidecar, keeping original timestamp and QC status.

    Works with the existing Auto Master engine without changing its public API.
    Never overwrites an existing export. Caller must supply the actual song title.
    """
    if not result.get('file'):
        raise ValueError('Auto Master did not supply an output file')
    source = Path(result['file'])
    if not source.is_file():
        raise FileNotFoundError(source)
    pattern = r'-(master|QC-REVIEW)-(\d{8}-\d{6}-\d{6})\.wav$'
    match = re.search(pattern, source.name, flags=re.I)
    if not match:
        raise ValueError(f'Unexpected mastering output filename: {source.name}')
    kind, timestamp = match.group(1), match.group(2)
    variant_part = f'_{safe_slug(variant)}' if variant else ''
    new_name = f'{safe_slug(title)}{variant_part}-{kind}-{timestamp}.wav'
    target = source.with_name(new_name)
    if target != source and target.exists():
        raise FileExistsError(f'Export already exists: {target}')
    old_sidecar = source.with_suffix('.qc.json')
    new_sidecar = target.with_suffix('.qc.json')
    if target != source and new_sidecar.exists():
        raise FileExistsError(f'QC report already exists: {new_sidecar}')
    if target != source:
        source.rename(target)
        if old_sidecar.is_file():
            try:
                old_sidecar.rename(new_sidecar)
            except OSError:
                target.rename(source)
                raise
    updated = dict(result)
    updated['file'] = str(target)
    if new_sidecar.exists():
        qc = json.loads(new_sidecar.read_text(encoding='utf-8'))
        qc['file'] = str(target)
        new_sidecar.write_text(json.dumps(qc, ensure_ascii=False, indent=2), encoding='utf-8')
    return updated
