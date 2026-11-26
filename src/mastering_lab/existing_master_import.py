"""Verify an existing locally mastered WAV before reusing it in Album Studio.

A QC sidecar alone is insufficient: it can be stale or refer to a modified
file. Re-measure the *actual* WAV using FFmpeg and validate PCM metadata.
No audio is modified, and files without valid sidecars remain waiting.
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path


class ExistingMasterError(ValueError):
    pass


def recognize_master(path, *, measurement_fn=None, probe_fn=None):
    from .auto_master import _measure, _probe_wav
    source=Path(path).resolve()
    if not source.is_file() or source.suffix.casefold()!='.wav':
        raise ExistingMasterError('A local WAV is required.')
    sidecar=source.with_suffix('.qc.json')
    if not sidecar.is_file():
        raise ExistingMasterError('No matching .qc.json report; independent QC is required.')
    try:
        report=json.loads(sidecar.read_text(encoding='utf-8'))
    except (OSError,UnicodeError,ValueError) as exc:
        raise ExistingMasterError('Unreadable QC sidecar.') from exc
    if not isinstance(report,dict) or report.get('status')!='qc_pass':
        raise ExistingMasterError('QC report does not indicate a pass.')
    recorded=report.get('file')
    if not isinstance(recorded,str) or Path(recorded).resolve()!=source:
        raise ExistingMasterError('QC report belongs to a different WAV.')
    expected=report.get('output')
    if not isinstance(expected,dict):
        raise ExistingMasterError('Missing output audio metadata.')
    probe=(probe_fn or _probe_wav)(source)
    for key in ('sample_rate','channels','frames','subtype'):
        if probe.get(key)!=expected.get(key):
            raise ExistingMasterError(f'WAV changed since QC: {key}.')
    if probe['channels']!=2 or probe['subtype']!='PCM_24' or probe['frames']<=0:
        raise ExistingMasterError('A valid stereo 24-bit PCM master is required.')
    if measurement_fn is None:
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:
            raise ExistingMasterError('FFmpeg is required to verify the imported master.')
        measured=_measure(ffmpeg,source)
    else:
        measured=measurement_fn(source)
    try:
        lufs=float(measured['input_i'])
        peak=float(measured['input_tp'])
        old_lufs=float(report['output_lufs'])
        old_peak=float(report['output_true_peak_dbtp'])
        target=float(report['target_true_peak_dbtp'])
    except (ValueError,TypeError,KeyError) as exc:
        raise ExistingMasterError('Incomplete independent QC measurements.') from exc
    if not all(map(math.isfinite,(lufs,peak,old_lufs,old_peak,target))):
        raise ExistingMasterError('Non-finite QC measurement.')
    if abs(lufs-old_lufs)>0.15 or abs(peak-old_peak)>0.15:
        raise ExistingMasterError('Measured audio no longer matches the QC report.')
    if not -20.0<=lufs<=-8.0 or peak>-1.0 or target>-1.0:
        raise ExistingMasterError('Measured loudness or true peak fails acceptance limits.')
    result=dict(report)
    result.update({'status':'qc_pass','file':str(source),
                   'output_lufs':lufs,'output_true_peak_dbtp':peak,
                   'album_import_verification':'independent_ffmpeg_qc_v1'})
    return result
