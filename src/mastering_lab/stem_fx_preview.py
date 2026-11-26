"""Non-destructive short Dry/Wet audition previews for individual stems.

Preview the SAME segment in A and B. B receives saturation and is RMS-matched
to A without ever boosting beyond the original peak ceiling; RMS is an
approximate comparison only (not perceived-loudness/EBU R128 certification).
The approved album premix process remains separate from these audition files.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import soundfile as sf

from .album_saturation_preview import process_saturation_wav, validate_settings

POLICY='stem-dry-wet-v1'
SEGMENT_SECONDS=18
CEILING=0.98


def _audition_segment(source, output):
    """Select an active ~18s window from five local samples, avoiding silence."""
    with sf.SoundFile(str(source)) as f:
        if f.channels not in (1,2) or f.samplerate<16000 or f.frames<512:
            raise ValueError('Stem preview needs a nonempty WAV, mono or stereo.')
        n=min(f.frames,int(f.samplerate*SEGMENT_SECONDS))
        probe=min(n, max(2048,int(f.samplerate*1.0)))
        options=[round((f.frames-n)*i/4) for i in range(5)]
        best=0
        strength=-1.
        for start in options:
            f.seek(min(f.frames-probe,start+max(0,(n-probe)//2)))
            sample=f.read(probe,dtype='float64',always_2d=True)
            energy=float(np.mean(sample**2)) if len(sample) else 0.
            if energy>strength:
                strength=energy
                best=start
        f.seek(best)
        with sf.SoundFile(str(output),'w',samplerate=f.samplerate,
                          channels=f.channels,subtype='PCM_24') as w:
            remaining=n
            while remaining:
                chunk=f.read(min(65536,remaining),dtype='float64',always_2d=True)
                if not np.isfinite(chunk).all():
                    raise ValueError('Stem has nonfinite audio samples.')
                if not len(chunk):
                    raise RuntimeError('Stem ended before preview segment completed.')
                w.write(chunk)
                remaining-=len(chunk)
        return {'start_ms':round(best*1000/f.samplerate),
                'duration_ms':round(n*1000/f.samplerate),
                'sample_rate':f.samplerate,'frames':n,'channels':f.channels}


def _level_match(raw, original, final):
    """Same-length RMS matching, no hidden limiter / hard clipping."""
    with sf.SoundFile(str(original)) as dry, sf.SoundFile(str(raw)) as wet:
        if (dry.channels!=wet.channels or dry.samplerate!=wet.samplerate
                or dry.frames!=wet.frames):
            raise ValueError('Dry and Wet preview must be aligned.')
        sum_dry=sum_wet=0.
        frames=0
        peak=0.
        while True:
            a=dry.read(65536,dtype='float64',always_2d=True)
            b=wet.read(65536,dtype='float64',always_2d=True)
            if not len(a):break
            sum_dry+=float(np.sum(a*a))
            sum_wet+=float(np.sum(b*b))
            peak=max(peak,float(np.max(np.abs(b))))
            frames+=a.size
        if not frames or sum_dry<1e-13 or sum_wet<1e-13:
            raise ValueError('Cannot audition a silent or empty stem.')
        target_gain=math.sqrt(sum_dry/sum_wet)
        gain=min(target_gain,CEILING/max(peak,1e-12))
        if gain<=0 or not math.isfinite(gain):
            raise RuntimeError('No safe gain for Wet preview.')
        dry.seek(0)
        wet.seek(0)
        with sf.SoundFile(str(final),'w',samplerate=dry.samplerate,
                          channels=dry.channels,subtype='PCM_24') as output:
            while True:
                b=wet.read(65536,dtype='float64',always_2d=True)
                if not len(b):break
                output.write(b*gain)
        relative_db=20*math.log10(max(gain,1e-12))
        matched=(abs(20*math.log10(max(target_gain/gain,1e-12)))<=.25)
        if not matched:
            raise RuntimeError('Wet cannot be RMS matched to Dry without approaching clip.')
        return round(relative_db,3)


def prepare_stem_ab_preview(source, cache_dir, *, style, drive, mix,
                            processor=None):
    """Make fixed aligned A/B files. Called in a background Qt worker."""
    validate_settings(style,drive,mix)
    source=Path(source).resolve(strict=True)
    if source.suffix.lower()!='.wav':
        raise ValueError('Stem A/B preview currently requires a WAV source.')
    stat=source.stat()
    key=hashlib.sha256(json.dumps(
        {'policy':POLICY,'source':str(source),'size':stat.st_size,
         'mtime':stat.st_mtime_ns,'style':style,
         'drive':float(drive),'mix':float(mix)},
        sort_keys=True).encode()).hexdigest()[:22]
    dest=Path(cache_dir).resolve()/key
    a=dest/'dry.wav'
    b=dest/'wet.wav'
    report_file=dest/'preview.json'
    if a.is_file() and b.is_file() and report_file.is_file():
        try:
            previous=json.loads(report_file.read_text(encoding='utf-8'))
            if previous.get('key')==key and a.stat().st_size>44 and b.stat().st_size>44:
                return previous
        except (OSError,ValueError):
            pass
    dest.mkdir(parents=True,exist_ok=True)
    dry_temp=dest/'.dry.partial.wav'
    wet_raw=dest/'.wet-raw.partial.wav'
    wet_temp=dest/'.wet.partial.wav'
    printer=processor or process_saturation_wav
    try:
        section=_audition_segment(source,dry_temp)
        printer(dry_temp,wet_raw,style=style,drive=drive,mix=mix)
        gain=_level_match(wet_raw,dry_temp,wet_temp)
        wet_temp.replace(b)
        dry_temp.replace(a)
        report={'key':key,'source':str(source),'dry':str(a),'wet':str(b),
                'status':'preview_only','style':style,'drive':float(drive),
                'mix':float(mix),'rms_compensation_db':gain,
                'rms_matched':True,'note':'Audition-only RMS match, NOT master LUFS/True Peak certification.',
                **section}
        partial=dest/'.preview.partial.json'
        partial.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        partial.replace(report_file)
        return report
    finally:
        for item in (dry_temp,wet_raw,wet_temp):
            item.unlink(missing_ok=True)
