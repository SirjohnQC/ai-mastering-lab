"""Package already-mastered album WAVs in their current track order."""
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .album_export_naming import safe_slug
from .auto_master import MasteringCancelled


def export_album_masters(project, destination, *, stop=None, progress=None):
    """Publish a new delivery folder only once every master was copied."""
    tracks = project['tracks']
    if not tracks:
        raise ValueError('Ajoute au moins une chanson à l’album.')
    sources = []
    unavailable = []
    for number, track in enumerate(tracks, 1):
        result = track.get('result') or {}
        title = track.get('title') or f'Piste {number}'
        source = Path(result.get('file') or '.')
        if (track.get('status') != 'qc_pass' or result.get('status') != 'qc_pass'
                or source.suffix.lower() != '.wav' or not source.is_file()
                or source.stat().st_size == 0):
            unavailable.append(f'{number:02d} · {title}')
        else:
            sources.append((title, source))
    if unavailable:
        raise ValueError('Masters QC manquants ou à vérifier :\n' + '\n'.join(unavailable))

    _check_cancelled(stop)
    destination = Path(destination).resolve(strict=True)
    title = project.get('album') or 'Album'
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    target = destination / f'{safe_slug(title)}-{stamp}-{uuid4().hex[:8]}'
    digits = max(2, len(str(len(sources))))
    manifest = {'schema_version': 1, 'album': title, 'tracks': []}
    with TemporaryDirectory(prefix='.frankenstem-export-', dir=destination) as staging:
        package = Path(staging) / 'masters'
        package.mkdir()
        for number, (song, source) in enumerate(sources, 1):
            _check_cancelled(stop)
            if progress is not None:
                progress(number - 1, len(sources), song)
            name = f'{number:0{digits}d}-{safe_slug(song)}.wav'
            before = source.stat()
            with source.open('rb') as reader, (package / name).open('xb') as writer:
                while block := reader.read(4 * 1024 * 1024):
                    _check_cancelled(stop)
                    writer.write(block)
            after = source.stat()
            if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                    or (package / name).stat().st_size != before.st_size):
                raise OSError(f'Master modifié pendant l’export : {song}')
            manifest['tracks'].append({'number': number, 'title': song, 'file': name})
        (package / 'tracklist.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        _check_cancelled(stop)
        if target.exists():
            raise FileExistsError(target)
        package.rename(target)
    return target


def _check_cancelled(stop):
    if stop is not None and stop.is_set():
        raise MasteringCancelled('Export album annulé.')
