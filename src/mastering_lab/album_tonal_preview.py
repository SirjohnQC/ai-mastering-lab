"""Conservative tonal-reference A/B preview, separate from level-only v0.25.6.

Broad spectral differences from Album Intelligence are *hints*, not EQ curves.
Render a gently EQ'd audition copy, loudness-match it to the source master,
independently verify true peak and never alter the QC-passed original.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

from .auto_master import _measure, _probe_wav

BAND_CENTERS = (90, 350, 1200, 4400, 11000)
MAX_FILTER_GAIN_DB = 1.25
MAX_FILTERS = 2
SPECTRAL_THRESHOLD_DB = 4.0
MAX_TRUSTED_DELTA_DB = 18.0
LOUDNESS_TOLERANCE_LU = 0.25
MAX_COMPENSATION_DB = 1.5
TP_CEILING_DBTP = -1.0
PREVIEW_POLICY = 'tonal-match-matched-loudness-v1'


def tonal_proposal(track):
    """Select <=2 cautious broad-band EQ moves. Do not infer exact correction."""
    if not isinstance(track, dict) or track.get('status') != 'measured':
        raise ValueError('Tonal matching needs an analyzed QC-pass master.')
    bands = track.get('relative_band_delta_db')
    if not isinstance(bands, list) or len(bands) != len(BAND_CENTERS):
        raise ValueError('Missing broad-band comparison against album reference.')
    if any(not isinstance(v, (float, int)) or
           isinstance(v, bool) or not math.isfinite(v) for v in bands):
        raise ValueError('Invalid broad-band measurements.')
    if any(abs(v) > MAX_TRUSTED_DELTA_DB for v in bands):
        raise ValueError('Extreme spectral difference: may reflect arrangement; no safe EQ guess.')
    # The upper band is especially vulnerable to sparsely populated material,
    # aliasing and mic noise; exclude it from automated matching for now.
    candidates = [(abs(delta), i, delta) for i, delta in enumerate(bands[:4])
                  if abs(delta) >= SPECTRAL_THRESHOLD_DB]
    candidates.sort(reverse=True)
    chosen = []
    for _, index, delta in candidates[:MAX_FILTERS]:
        # Gently oppose the measured *relative* energy difference, never
        # translate the band difference literally into a plugin gain.
        gain = round(max(-MAX_FILTER_GAIN_DB,
                         min(MAX_FILTER_GAIN_DB, -0.18 * delta)), 2)
        if abs(gain) >= 0.25:
            chosen.append({'band_index':index, 'frequency_hz':BAND_CENTERS[index],
                           'gain_db':gain, 'width_octaves':1.0,
                           'relative_difference_db':round(float(delta),2)})
    if not chosen:
        raise ValueError('No reliable, meaningful tonal difference to preview.')
    return {'kind':'tonal_eq_preview', 'filters':chosen,
            'disclaimer':'Approximate broad-band EQ experiment only. Reference may differ artistically.'}


def _render(ffmpeg, source, output, filters):
    args=[ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-y',
          '-i',str(source),'-map','0:a:0','-vn','-af',filters,
          '-c:a','pcm_s24le',str(output)]
    result=subprocess.run(args,capture_output=True,text=True,timeout=900,check=False)
    if result.returncode or not output.is_file():
        raise RuntimeError('FFmpeg EQ preview failed: '+result.stderr[-700:])


def _metrics(fn, path):
    m=fn(path)
    try:
        lufs=float(m['input_i'])
        tp=float(m['input_tp'])
    except (KeyError,ValueError,TypeError) as exc:
        raise RuntimeError('Incomplete independent loudness/TP measurement.') from exc
    if not math.isfinite(lufs) or not math.isfinite(tp):
        raise RuntimeError('Invalid measured LUFS or true peak.')
    return lufs,tp


def render_tonal_preview(master_path, report_track, cache_dir, *,
                         ffmpeg_path=None, measure_fn=None):
    """Produce B separately, match its loudness to A, enforce TP, cache safely."""
    source=Path(master_path).resolve(strict=True)
    if not source.is_file() or source.suffix.lower() != '.wav':
        raise ValueError('Original master must be a WAV.')
    meta=_probe_wav(source)
    if meta['channels']!=2 or meta['frames']<=0:
        raise ValueError('Original must be a nonempty stereo WAV.')
    suggestion=tonal_proposal(report_track)
    ffmpeg=ffmpeg_path or shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('Local FFmpeg is required.')
    measure=measure_fn or (lambda path:_measure(ffmpeg,path))
    original_lufs,original_tp=_metrics(measure,source)
    if original_tp>TP_CEILING_DBTP:
        raise ValueError('Original exceeds -1 dBTP. Check original QC first.')
    target=Path(cache_dir).resolve()
    target.mkdir(parents=True,exist_ok=True)
    stat=source.stat()
    fingerprint=json.dumps({
        'source':str(source),'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,
        'policy':PREVIEW_POLICY,'filters':suggestion['filters'],
        'original_lufs':round(original_lufs,3),'original_tp':round(original_tp,3)
    },sort_keys=True)
    digest=hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:20]
    output=target / f'album-tonal-ab-{digest}.wav'
    manifest=output.with_suffix('.json')
    if output.is_file() and manifest.is_file():
        try:
            cached=json.loads(manifest.read_text(encoding='utf-8'))
            if (cached.get('fingerprint')==fingerprint
                    and cached.get('status')=='preview_only'
                    and output.stat().st_size>44
                    and float(cached['verified_true_peak_dbtp'])<=TP_CEILING_DBTP
                    and abs(float(cached['measured_lufs'])-original_lufs)<=LOUDNESS_TOLERANCE_LU):
                return cached
        except (OSError,ValueError,KeyError,TypeError):
            pass
    intermediate=target / f'.album-tonal-ab-{digest}.eq.partial.wav'
    temp=target / f'.album-tonal-ab-{digest}.partial.wav'
    eq=','.join(f'equalizer=f={f["frequency_hz"]}:t=o:w={f["width_octaves"]:.2f}:g={f["gain_db"]:.2f}'
                for f in suggestion['filters'])
    try:
        _render(ffmpeg,source,intermediate,eq)
        intermediate_lufs,_=_metrics(measure,intermediate)
        compensation=original_lufs-intermediate_lufs
        if abs(compensation)>MAX_COMPENSATION_DB:
            raise RuntimeError('EQ affects loudness too much for trustworthy A/B matching.')
        # Render a final PCM24 file without destructive limiting. If it cannot
        # satisfy the peak ceiling *and* matched loudness, reject B.
        filt=eq + f',volume={compensation:+.4f}dB'
        _render(ffmpeg,source,temp,filt)
        rendered=_probe_wav(temp)
        if (rendered['channels']!=2 or rendered['sample_rate']!=meta['sample_rate']
                or rendered['frames']!=meta['frames'] or rendered['subtype']!='PCM_24'):
            raise RuntimeError('Tonal preview format/duration mismatch.')
        lufs,tp=_metrics(measure,temp)
        if tp>TP_CEILING_DBTP:
            raise RuntimeError('Tonal preview exceeds -1 dBTP; cannot safely compare B.')
        if abs(lufs-original_lufs)>LOUDNESS_TOLERANCE_LU:
            raise RuntimeError('Tonal preview loudness mismatch; B is not level-matched.')
        temp.replace(output)
        record={'status':'preview_only','file':str(output),
                'source_master':str(source),'fingerprint':fingerprint,
                'kind':'tonal_eq_preview','eq_filters':suggestion['filters'],
                'gain_db':round(compensation,4),
                'original_lufs':round(original_lufs,3),
                'measured_lufs':round(lufs,3),
                'verified_true_peak_dbtp':round(tp,3),
                'approved':False,
                'warning':'A/B tonal audition only, not a certified exported master; original untouched.'}
        pending=manifest.with_suffix('.json.partial')
        pending.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        pending.replace(manifest)
        return record
    finally:
        intermediate.unlink(missing_ok=True)
        temp.unlink(missing_ok=True)
