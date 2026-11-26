"""Per-stem Dry/Wet audition only; whole-file renders, no source writes."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf

from .album_saturation_preview import process_saturation_wav,validate_settings

def _level(path, block=65536):
    total=0.
    frames=0
    peak=0.
    with sf.SoundFile(str(path)) as f:
        for chunk in f.blocks(blocksize=block,dtype='float64',always_2d=True):
            if not np.isfinite(chunk).all(): raise ValueError('Nonfinite audio')
            total+=float(np.sum(chunk*chunk))
            frames+=chunk.size
            peak=max(peak,float(np.max(np.abs(chunk))))
        return (math.sqrt(total/max(frames,1)),peak,
                (f.samplerate,f.channels,f.frames))

def create_stem_preview(source, cache_dir, *, style='tape', drive=.6, mix=.12,
                        processor=None):
    """Render separate wet preview at approximately matched RMS and safe sample peak.

    RMS matching is a *preview* alignment, not integrated LUFS measurement.
    Reject rather than clamp if wet would clip. Never change source WAV.
    """
    style,drive,mix=validate_settings(style,drive,mix)
    original=Path(source).resolve(strict=True)
    if original.suffix.lower()!='.wav':
        raise ValueError('Stem audition currently supports WAV only.')
    original_rms,original_peak,format_a=_level(original)
    if original_rms<1e-6:
        raise ValueError('Stem is silent; no useful A/B preview.')
    folder=Path(cache_dir).resolve()
    folder.mkdir(parents=True,exist_ok=True)
    stat=original.stat()
    data=json.dumps({'version':2,'source':str(original),'size':stat.st_size,
                     'mtime':stat.st_mtime_ns,'style':style,'drive':drive,'mix':mix},
                    sort_keys=True)
    key=hashlib.sha256(data.encode()).hexdigest()[:20]
    target=folder/f'fx-{key}.wav'
    manifest=target.with_suffix('.json')
    if target.is_file() and manifest.is_file():
        try:
            result=json.loads(manifest.read_text(encoding='utf-8'))
            if (result.get('identity')==data and target.stat().st_size>44
                    and _level(target)[2]==format_a):
                return result
        except (OSError,ValueError,KeyError):
            pass
    raw=folder/f'.fx-{key}.raw.partial.wav'
    part=folder/f'.fx-{key}.final.partial.wav'
    try:
        (processor or process_saturation_wav)(
            original,raw,style=style,drive=drive,mix=mix)
        wet_rms,wet_peak,format_b=_level(raw)
        if format_a!=format_b:
            raise ValueError('Stem preview length, sample rate or channels changed.')
        gain=original_rms/max(wet_rms,1e-12)
        if not .8<=gain<=1.25:
            raise ValueError('Too much gain needed for fair Dry/Wet audition.')
        if wet_peak*gain>=.99:
            raise ValueError('Dry/Wet preview would clip at matched level.')
        with sf.SoundFile(str(raw)) as read, sf.SoundFile(
            str(part),'w',samplerate=format_a[0],channels=format_a[1],
            subtype='PCM_24') as write:
            for chunk in read.blocks(blocksize=65536,dtype='float64',
                                     always_2d=True):
                write.write(chunk*gain)
        actual_rms,actual_peak,final_format=_level(part)
        if final_format!=format_a or actual_peak>=.99:
            raise ValueError('Unsafe preview format or peak.')
        if abs(20*math.log10(actual_rms/original_rms))>.2:
            raise ValueError('Dry/Wet RMS matching failed.')
        part.replace(target)
        result={'file':str(target),'original':str(original),'identity':data,
                'status':'audition_only','style':style,'drive':drive,'mix':mix,
                'rms_difference_db':round(20*math.log10(actual_rms/original_rms),3),
                'sample_peak_dbfs':round(20*math.log10(max(actual_peak,1e-12)),3),
                'note':'RMS-matched stem audition, NOT certified LUFS/True Peak mastering.'}
        temp=manifest.with_suffix('.json.tmp')
        temp.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        temp.replace(manifest)
        return result
    finally:
        raw.unlink(missing_ok=True)
        part.unlink(missing_ok=True)
