"""Experimental, non-destructive, oversampled saturation A/B preview.

Tube/Tape/Soft Clip names describe *approximate digital transfer curves*, not
physical analog hardware models. Final B is matched to A's measured integrated
LUFS and rejected unless true peak remains <= -1 dBTP.

Audio is processed in bounded blocks; NEVER written to source master.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil

from .auto_master import _measure, _probe_wav
from .album_tonal_preview import (
    _metrics, _render, LOUDNESS_TOLERANCE_LU,
    MAX_COMPENSATION_DB, TP_CEILING_DBTP,
)

SATURATION_STYLES = ('tape', 'tube', 'softclip')
SAFE_STRENGTHS = (1.0, .75, .5, .25)
MAX_DRIVE = 2.5
MAX_MIX = .4
BLOCK = 65536
OVERLAP = 1536
POLICY = 'oversampled-saturation-ab-v1'


def validate_settings(style, drive, mix):
    if style not in SATURATION_STYLES:
        raise ValueError('Choose Tape, Tube or Soft Clip.')
    if (not isinstance(drive,(float,int)) or isinstance(drive,bool)
            or not math.isfinite(drive) or not 0.1<=drive<=MAX_DRIVE):
        raise ValueError('Drive must be between 0.1 and 2.5.')
    if (not isinstance(mix,(float,int)) or isinstance(mix,bool)
            or not math.isfinite(mix) or not 0.0<mix<=MAX_MIX):
        raise ValueError('Wet mix must be above zero and no more than 40%.')
    return style,float(drive),float(mix)


def _shape(x, style, drive):
    import numpy as np
    if style == 'tape':
        # Symmetric tanh: soft saturation with comparatively few upper partials.
        y=np.tanh(x*(1.0+.8*drive))
        return y/np.tanh(1.0+.8*drive)
    if style == 'tube':
        # Mild asymmetric curve generates some even-harmonic content.
        shift=0.14*drive
        gain=1.0+drive
        return (np.tanh(gain*(x+shift))-np.tanh(gain*shift))/gain
    # Cubic continuous soft knee. Avoid hard clipping discontinuity.
    z=np.clip(x*(1.0+.65*drive),-1.0,1.0)
    return z-z**3/3


def process_saturation_wav(source, destination, *, style, drive, mix):
    """4x oversampling reduces aliasing for this prototype transfer curve."""
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    validate_settings(style,drive,mix)
    with sf.SoundFile(str(source)) as read:
        if read.channels!=2 or read.frames<=0:
            raise ValueError('Saturation requires a nonempty stereo WAV.')
        with sf.SoundFile(str(destination),'w',samplerate=read.samplerate,
                          channels=2,format='WAV',subtype='PCM_24') as write:
            offset=0
            while offset<read.frames:
                start=max(0,offset-OVERLAP)
                end=min(read.frames,offset+BLOCK+OVERLAP)
                read.seek(start)
                chunk=read.read(end-start,dtype='float64',always_2d=True)
                if not np.isfinite(chunk).all():
                    raise ValueError('Source contains non-finite audio samples.')
                up=resample_poly(chunk,4,1,axis=0)
                wet=_shape(up,style,drive)
                down=resample_poly(wet,1,4,axis=0)
                # Keep the original PCM bit depth; any residual oversampling
                # boundary error is outside the kept overlap region.
                left=offset-start
                length=min(BLOCK,read.frames-offset)
                dry=chunk[left:left+length]
                processed=down[left:left+length]
                combined=dry*(1.0-mix)+processed*mix
                if not np.isfinite(combined).all():
                    raise ValueError('Saturation produced non-finite samples.')
                write.write(np.clip(combined,-1.0,1.0))
                offset+=length


def render_saturation_preview(master_path, report_track, cache_dir, *,
                              style='tape', drive=1.0, mix=.2,
                              ffmpeg_path=None, measure_fn=None,
                              processor_fn=None):
    """A/B-only saturation; independent EBU R128 checks and cautious fallback."""
    style,drive,mix=validate_settings(style,drive,mix)
    if not isinstance(report_track,dict) or report_track.get('status')!='measured':
        raise ValueError('Select a song with a QC-pass album analysis first.')
    source=Path(master_path).resolve(strict=True)
    if source.suffix.lower()!='.wav':
        raise ValueError('A mastered WAV is required.')
    metadata=_probe_wav(source)
    if (metadata['channels']!=2 or metadata['subtype']!='PCM_24'
            or metadata['frames']<=0):
        raise ValueError('Stereo 24-bit PCM master required.')
    ffmpeg=ffmpeg_path or shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('Local FFmpeg is required for final QC.')
    measure=measure_fn or (lambda p:_measure(ffmpeg,p))
    original_lufs,original_tp=_metrics(measure,source)
    if original_tp>TP_CEILING_DBTP:
        raise ValueError('Original master true peak exceeds safety ceiling.')
    dest=Path(cache_dir).resolve()
    dest.mkdir(parents=True,exist_ok=True)
    stat=source.stat()
    fingerprint=json.dumps({
        'policy':POLICY,'file':str(source),'size':stat.st_size,'mtime':stat.st_mtime_ns,
        'style':style,'drive':drive,'mix':mix,
        'a_lufs':round(original_lufs,3),'a_tp':round(original_tp,3),
    },sort_keys=True)
    key=hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:20]
    final=dest/f'album-saturation-ab-{key}.wav'
    manifest=final.with_suffix('.json')
    if final.is_file() and manifest.is_file():
        try:
            old=json.loads(manifest.read_text(encoding='utf-8'))
            if (old['fingerprint']==fingerprint and old['status']=='preview_only'
                    and final.stat().st_size>44
                    and old['verified_true_peak_dbtp']<=TP_CEILING_DBTP
                    and abs(old['measured_lufs']-original_lufs)<=LOUDNESS_TOLERANCE_LU):
                return old
        except (OSError,TypeError,KeyError,ValueError):
            pass
    raw=dest/f'.saturation-{key}.raw.partial.wav'
    rendered=dest/f'.saturation-{key}.partial.wav'
    processor=processor_fn or process_saturation_wav
    try:
        last_tp=None
        success=None
        for strength in SAFE_STRENGTHS:
            actual_drive=max(.1,drive*strength)
            actual_mix=mix*strength
            processor(source,raw,style=style,drive=actual_drive,mix=actual_mix)
            raw_lufs,_=_metrics(measure,raw)
            compensation=original_lufs-raw_lufs
            if abs(compensation)>MAX_COMPENSATION_DB:
                raise RuntimeError('Saturation changed loudness too much to compare fairly.')
            _render(ffmpeg,raw,rendered,f'volume={compensation:+.4f}dB')
            probe=_probe_wav(rendered)
            if (probe['channels']!=metadata['channels']
                    or probe['sample_rate']!=metadata['sample_rate']
                    or probe['frames']!=metadata['frames']
                    or probe['subtype']!='PCM_24'):
                raise RuntimeError('Rendered saturation WAV does not match master format.')
            lufs,tp=_metrics(measure,rendered)
            last_tp=tp
            if abs(lufs-original_lufs)>LOUDNESS_TOLERANCE_LU:
                raise RuntimeError('B loudness could not be matched to A.')
            if tp<=TP_CEILING_DBTP:
                success=(strength,actual_drive,actual_mix,compensation,lufs,tp)
                break
        if success is None:
            raise RuntimeError(
                'No safe saturation B: true peak above -1 dBTP at all tested strengths'
                f' (last measured {last_tp:.2f} dBTP).')
        strength,actual_drive,actual_mix,compensation,lufs,tp=success
        rendered.replace(final)
        report={
            'status':'preview_only','approved':False,'file':str(final),
            'source_master':str(source),'fingerprint':fingerprint,
            'kind':'creative_saturation_preview','mode':'saturation',
            'saturation_style':style,'drive':round(actual_drive,4),
            'wet_mix':round(actual_mix,4),'intensity':strength,
            'requested_drive':drive,'requested_wet_mix':mix,
            'gain_db':round(compensation,4),
            'original_lufs':round(original_lufs,3),
            'measured_lufs':round(lufs,3),
            'verified_true_peak_dbtp':round(tp,3),
            'warning':'Optional digital saturation audition, not a final certified master.',
        }
        pending=manifest.with_suffix('.json.partial')
        pending.write_text(json.dumps(report,ensure_ascii=False,indent=2),
                           encoding='utf-8')
        pending.replace(manifest)
        return report
    finally:
        raw.unlink(missing_ok=True)
        rendered.unlink(missing_ok=True)
