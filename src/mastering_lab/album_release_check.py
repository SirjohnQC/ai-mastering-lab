"""Scan album masters in track order without changing their audio or approval."""
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from .auto_master import MasteringCancelled
from .release_preflight import run_preflight


def check_album_release(tracks, target, *, stop=None, progress=None):
    rows = []
    for index, track in enumerate(tracks, 1):
        _check_cancelled(stop)
        title = track.get('title') or f'Piste {index}'
        if progress is not None:
            progress(index - 1, len(tracks), title)
        result = track.get('result') or {}
        path = result.get('file')
        row = {'number': index, 'title': title, 'file': path}
        if track.get('status') not in ('qc_pass', 'needs_review') or not path:
            row.update(status='unavailable', error='Aucun master actuel. Lance Auto Produce Album.')
        else:
            try:
                report = run_preflight(path, write_report=False, stop=stop)
                row.update(status=report['status'], preflight=report)
            except MasteringCancelled:
                raise
            except Exception as exc:
                row.update(status='unavailable', error=str(exc))
        rows.append(row)

    _check_cancelled(stop)
    transitions = []
    for left, right in zip(rows, rows[1:]):
        left_loudness = left.get('preflight', {}).get('loudness')
        right_loudness = right.get('preflight', {}).get('loudness')
        if left_loudness and right_loudness:
            delta = right_loudness['integrated_lufs'] - left_loudness['integrated_lufs']
            if abs(delta) >= 2:
                transitions.append({'from': left['number'], 'to': right['number'],
                                    'delta_lufs': round(delta, 2)})
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema_version': 1, 'tracks': rows, 'listen_transitions': transitions}
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
        _check_cancelled(stop)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return report


def _check_cancelled(stop):
    if stop is not None and stop.is_set():
        raise MasteringCancelled('Contrôle avant sortie annulé.')


def format_album_release(report):
    lines = []
    labels = {'technical_pass': 'OK', 'technical_pass_with_notes': 'Notes',
              'needs_review': 'À vérifier', 'unavailable': 'Indisponible'}
    for row in report['tracks']:
        lines.append(f"{row['number']:02d}  {row['title']} · {labels[row['status']]}")
        check = row.get('preflight')
        if check is None:
            lines.extend((row['error'], ''))
            continue
        loudness = check['loudness']
        if loudness:
            lines.append(f"{loudness['integrated_lufs']:.2f} LUFS · "
                         f"{loudness['true_peak_dbtp']:.2f} dBTP")
        audio = check['audio']
        lines.append(f"Silence début / fin  {audio['initial_silence_seconds']:.2f} s / "
                     f"{audio['final_silence_seconds']:.2f} s  ·  "
                     f"{audio['clipped_frames']} frame(s) au maximum numérique")
        lines.extend(check['issues'] + check['warnings'])
        lines.append('')
    if report['listen_transitions']:
        lines.append('Enchaînements à écouter · écart de niveau intégré ≥ 2 LU')
        for transition in report['listen_transitions']:
            lines.append(f"{transition['from']:02d} → {transition['to']:02d}   "
                         f"{transition['delta_lufs']:+.2f} LU")
    return '\n'.join(lines)
