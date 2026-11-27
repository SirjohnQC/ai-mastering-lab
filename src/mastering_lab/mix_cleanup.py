"""Find and archive complete superseded Auto Mix sessions."""
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path

from .mix_comparison import load_comparison


def _session_sources(manifest):
    paths, _ = load_comparison(manifest)
    source_sets = []
    for wav in paths.values():
        if wav.parent != manifest.parent:
            raise ValueError('Session audio is outside its render folder.')
        report = json.loads(wav.with_suffix('.mix.json').read_text(encoding='utf-8'))
        tracks = report['tracks']
        sources = frozenset(Path(track['file']).resolve() for track in tracks)
        if not sources:
            raise ValueError('Session has no stem provenance.')
        source_sets.append(sources)
    if any(sources != source_sets[0] for sources in source_sets[1:]):
        raise ValueError('Session variants use different stems.')
    return source_sets[0]


def _protected_sessions(root, sessions, protected_paths):
    protected = {Path(path).resolve() for path in protected_paths if path}
    reports = [root / 'settings' / 'album_project.json',
               root / 'settings' / 'pro_c3_unified_cache.json']
    reports.extend((root / 'sound' / 'output').rglob('*.qc.json'))
    # A QC report can point to the session itself or a compressed derivative.
    # Keep sessions mentioned in those on-disk records, even if no player is open.
    for report in reports:
        try:
            if report.is_file():
                data = report.read_text(encoding='utf-8').replace('\\\\', '/').casefold()
                for folder in sessions:
                    if folder.as_posix().casefold() in data:
                        protected.add(folder)
        except (OSError, UnicodeError):
            continue
    return {folder for folder in sessions if any(path == folder or folder in path.parents
                                                 for path in protected)}


def superseded_sessions(auto_mix, root, *, protected_paths=()):
    """Keep the newest complete render for each exact set of source stems."""
    auto_mix, root = Path(auto_mix).resolve(), Path(root).resolve()
    cache = root / 'sound' / 'output' / 'stem_plus'
    if auto_mix.name != 'auto_mix' or auto_mix.parent.parent != cache.resolve():
        raise ValueError('Only managed Auto Mix sessions can be archived.')
    groups = defaultdict(list)
    for manifest in auto_mix.glob('session-*/comparison.json'):
        if manifest.parent.is_symlink() or manifest.is_symlink():
            continue
        try:
            sources = _session_sources(manifest)
            groups[sources].append((manifest.stat().st_mtime_ns, manifest.parent))
        except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError):
            continue
    folders = [folder for sessions in groups.values() for _, folder in sessions]
    if not any(len(sessions) > 1 for sessions in groups.values()):
        return []
    protected = _protected_sessions(root, folders, protected_paths)
    old = []
    for sessions in groups.values():
        sessions.sort(reverse=True)
        old.extend((stamp, folder) for stamp, folder in sessions[1:] if folder not in protected)
    return sorted(old, reverse=True)


def archive_superseded(auto_mix, root, selected, *, protected_paths=()):
    """Revalidate the preview and move complete folders as reversible units."""
    auto_mix = Path(auto_mix).resolve()
    current = set(superseded_sessions(auto_mix, root, protected_paths=protected_paths))
    if not set(selected).issubset(current):
        raise ValueError('Auto Mix sessions changed. Reopen cleanup to refresh the preview.')
    if not selected:
        return [], []
    archive = auto_mix / '_archive'
    if archive.is_symlink():
        raise ValueError('Auto Mix archive must be a local folder.')
    archive.mkdir(exist_ok=True)
    batch = archive / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    batch.mkdir()
    moved, errors = [], []
    for _, folder in selected:
        target = batch / folder.name
        try:
            folder.rename(target)
            moved.append(target)
        except OSError as exc:
            errors.append(f'{folder.name}: {exc}')
    if not moved:
        batch.rmdir()
    return moved, errors
