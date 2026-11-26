"""Safe, local, optional album A/B gain preview (not EQ or new mastering).

Makes a conservative LEVEL ONLY alternate with bounded gain and a remeasured
true-peak ceiling. If no safe useful adjustment exists, refuses to render.
Never overwrites a master or treats an audition WAV as a QC-certified export.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .auto_master import _measure, _probe_wav

MAX_CHANGE_DB = 1.0
TRUE_PEAK_CEILING = -1.0
RENDER_HEADROOM = -1.2


def proposal(track: dict, master_path: Path) -> dict:
    """Conservative loudness review only; do not interpret FFT as EQ gain."""
    if track.get('status') != 'measured':
        raise ValueError('A QC-approved measured master is required.')
    delta = track.get('lufs_delta')
    peak = track.get('true_peak_dbtp')
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (delta, peak)):
        raise ValueError('Missing or invalid loudness/true-peak measurements.')
    if peak > TRUE_PEAK_CEILING:
        raise ValueError('Original master is already above the true-peak ceiling.')
    if abs(delta) <= 0.5:
        raise ValueError('Loudness already close to reference; no preview needed.')
    # Reference matching can imply boosting: keep positive gain under measured
    # peak headroom and bound absolute change. Negative gain is also limited.
    suggested = max(-MAX_CHANGE_DB, min(MAX_CHANGE_DB, -delta))
    if suggested > 0:
        suggested = min(suggested, max(0.0, RENDER_HEADROOM-peak))
    if abs(suggested) < 0.15:
        raise ValueError('No useful level change available within safe headroom.')
    return {'gain_db':round(suggested, 2), 'kind':'level_only',
            'note':'Level-only audition, not EQ or reference-matched mastering.'}


def render_preview(master_path, report_track, cache_dir, *, ffmpeg_path=None, measure_fn=None):
    master=Path(master_path).resolve(strict=True)
    if not master.is_file() or master.suffix.lower()!='.wav':
        raise ValueError('Valid source master WAV required.')
    meta=_probe_wav(master)
    if meta['channels']!=2 or meta['frames']<=0:
        raise ValueError('Stereo WAV master required.')
    suggestion=proposal(report_track, master)
    ffmpeg=ffmpeg_path or shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('FFmpeg required to render and independently check preview.')
    cache=Path(cache_dir).resolve()
    cache.mkdir(parents=True,exist_ok=True)
    stat=master.stat()
    fingerprint=json.dumps({'source':str(master),'size':stat.st_size,
        'mtime_ns':stat.st_mtime_ns,'gain':suggestion['gain_db'],
        'policy':'level-only-v1'},sort_keys=True)
    key=hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:20]
    output=cache / f'album-ab-{key}.wav'
    manifest=output.with_suffix('.json')
    if output.is_file() and manifest.is_file():
        try:
            previous=json.loads(manifest.read_text(encoding='utf-8'))
            if (previous.get('fingerprint')==fingerprint
                    and previous.get('verified_true_peak_dbtp')<=TRUE_PEAK_CEILING
                    and output.stat().st_size>44):
                return previous
        except (OSError,TypeError,ValueError):
            pass
    temporary=cache / f'.album-ab-{key}.partial.wav'
    try:
        cmd=[ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-y',
            '-i',str(master),'-map','0:a:0','-vn',
            '-af',f'volume={suggestion["gain_db"]:.2f}dB',
            '-c:a','pcm_s24le',str(temporary)]
        completed=subprocess.run(cmd,capture_output=True,text=True,timeout=900,check=False)
        if completed.returncode != 0 or not temporary.is_file():
            raise RuntimeError('FFmpeg preview failed: '+completed.stderr[-600:])
        probe=_probe_wav(temporary)
        if (probe['channels']!=2 or probe['sample_rate']!=meta['sample_rate']
                or probe['frames']!=meta['frames'] or probe['subtype']!='PCM_24'):
            raise RuntimeError('Preview format/duration mismatch.')
        measured=(measure_fn or (lambda path:_measure(ffmpeg,path)))(temporary)
        actual_tp=float(measured['input_tp'])
        actual_lufs=float(measured['input_i'])
        if (not math.isfinite(actual_tp) or not math.isfinite(actual_lufs)
                or actual_tp>TRUE_PEAK_CEILING):
            raise RuntimeError('Preview failed independent true-peak QC.')
        temporary.replace(output)
        result={'status':'preview_only','file':str(output),
            'source_master':str(master),'fingerprint':fingerprint,
            'gain_db':suggestion['gain_db'],'verified_true_peak_dbtp':actual_tp,
            'measured_lufs':actual_lufs,'approved':False,
            'warning':'A/B audition only. Original master untouched. Not a distribution-ready certified master.'}
        tmp_manifest=manifest.with_suffix('.json.partial')
        tmp_manifest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp_manifest.replace(manifest)
        return result
    finally:
        temporary.unlink(missing_ok=True)
