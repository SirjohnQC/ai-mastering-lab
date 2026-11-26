"""Read-only album consistency analysis around a user-selected master.

Never alters audio, never uploads WAVs and never claims to judge musical
quality. Uses a bounded sample of FFT windows for broad spectral comparison.
Integrated LUFS/true peak come only from QC reports, NOT approximated from RMS.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

BANDS = ((40,160),(160,600),(600,2400),(2400,8000),(8000,18000))
MAX_SLICES = 72
FFT_SIZE = 8192
MAX_TRACKS = 80


def _number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _master_for(row):
    if row.get('status') != 'qc_pass':
        return None
    result = row.get('result')
    if not isinstance(result,dict) or result.get('status') != 'qc_pass':
        return None
    path = result.get('file')
    if not isinstance(path,str) or not path.lower().endswith('.wav'):
        return None
    p = Path(path).resolve()
    if not p.is_file():
        return None
    if not (_number(result.get('output_lufs')) and
            _number(result.get('output_true_peak_dbtp'))):
        return None
    return p


def spectrum_profile(source: Path):
    """Coarse level-independent spectrum, sampled across the whole local WAV."""
    path = Path(source).resolve(strict=True)
    with sf.SoundFile(str(path)) as f:
        if f.channels != 2 or f.samplerate < 32000 or f.frames < FFT_SIZE:
            raise ValueError('Requires nonempty stereo PCM at >=32 kHz.')
        offsets = np.linspace(0, f.frames - FFT_SIZE,
                              num=min(MAX_SLICES,max(6,f.frames//(f.samplerate*3))),
                              dtype='int64')
        freqs = np.fft.rfftfreq(FFT_SIZE,1/f.samplerate)
        sums = np.zeros(len(BANDS),dtype='float64')
        active = 0
        window = np.hanning(FFT_SIZE)
        for offset in offsets:
            f.seek(int(offset))
            block = f.read(FFT_SIZE,dtype='float32',always_2d=True)
            if len(block) != FFT_SIZE or not np.isfinite(block).all():
                continue
            mono = np.mean(block.astype('float64'),axis=1)
            if np.sqrt(np.mean(mono**2)) < 10**(-52/20):
                continue
            power = np.abs(np.fft.rfft(mono*window))**2
            for index,(low,high) in enumerate(BANDS):
                sums[index] += float(power[(freqs>=low)&(freqs<high)].sum())
            active += 1
    if not active or sums.sum() <= 1e-18:
        raise ValueError('No usable active audio windows.')
    shares = sums/sums.sum()
    return {'band_shares':[round(float(x),7) for x in shares],
            'bands_hz':[list(b) for b in BANDS],
            'sampled_windows':active,
            'note':'Relative sampled FFT energy (not perceived tonal balance or EQ advice).'}


def compare_album(project: dict, *, reference_index: int | None = None, external_reference_wav=None, profile_fn=None, external_measure_fn=None):
    rows = project.get('tracks',[])
    if not isinstance(rows,list) or not 1 <= len(rows) <= MAX_TRACKS:
        raise ValueError('Album must have 1-80 tracks.')
    if external_reference_wav is not None:
        from .album_external_reference import external_reference_metrics
        ref_result = external_reference_metrics(external_reference_wav, measurer=external_measure_fn)
        reference_path = Path(ref_result['file'])
        reference_index = None
        reference_title = reference_path.stem
    else:
        if not isinstance(reference_index,int) or not 0 <= reference_index < len(rows):
            raise ValueError('Choose a valid album reference track.')
        reference_path = _master_for(rows[reference_index])
        if reference_path is None:
            raise ValueError('The reference requires a completed QC-pass master WAV.')
        ref_result = rows[reference_index]['result']
        reference_title = rows[reference_index].get('title','')
    profile = profile_fn or spectrum_profile
    ref_spec = profile(reference_path)
    ref_shares = np.asarray(ref_spec['band_shares'],dtype='float64')
    if ref_shares.shape!=(len(BANDS),) or not np.isfinite(ref_shares).all() or np.any(ref_shares<0):
        raise ValueError('Invalid reference spectrum.')
    evaluations = []
    for index,row in enumerate(rows):
        file = _master_for(row)
        if file is None:
            evaluations.append({'index':index,'title':row.get('title',''),
                                'status':'not_ready','note':'No completed QC-pass master.'})
            continue
        try:
            candidate = profile(file)
            shares = np.asarray(candidate['band_shares'],dtype='float64')
            if shares.shape!=ref_shares.shape or not np.isfinite(shares).all() or np.any(shares<0):
                raise ValueError('Invalid spectrum.')
            # Level-independent relative band comparisons in decibels;
            # intentionally no unverified "automatic EQ" suggestions.
            band_deltas = [round(10*math.log10(max(float(a),1e-9)/max(float(b),1e-9)),2)
                           for a,b in zip(shares,ref_shares)]
            result = row['result']
            delta_lufs = round(result['output_lufs']-ref_result['output_lufs'],2)
            delta_tp = round(result['output_true_peak_dbtp']-ref_result['output_true_peak_dbtp'],2)
            flags = []
            if abs(delta_lufs)>1.5:
                flags.append('loudness_review')
            if max(abs(x) for x in band_deltas)>4.0:
                flags.append('spectrum_review')
            if result['output_true_peak_dbtp']>-1.0:
                flags.append('true_peak_review')
            evaluations.append({'index':index,'title':row.get('title',''),
                                'status':'reference' if index==reference_index else 'measured',
                                'lufs':result['output_lufs'],
                                'true_peak_dbtp':result['output_true_peak_dbtp'],
                                'lufs_delta':delta_lufs,'true_peak_delta':delta_tp,
                                'relative_band_delta_db':band_deltas,
                                'flags':flags})
        except (OSError,ValueError,RuntimeError) as exc:
            evaluations.append({'index':index,'title':row.get('title',''),
                                'status':'analysis_error','note':f'{type(exc).__name__}: {exc}'})
    return {'schema_version':1,'album':project.get('album','Album'),
            'reference_index':reference_index,
            'reference_title':reference_title,
            'reference_kind':'standalone_wav' if external_reference_wav is not None else 'album_qc_master',
            'bands_hz':[list(x) for x in BANDS],'tracks':evaluations,
            'disclaimer':('Read-only mastering comparison. Relative spectrum from sampled FFTs; '
                          'LUFS and true peak from existing QC reports. Differences may be artistic. '
                          'No files modified, no release certified.')}
