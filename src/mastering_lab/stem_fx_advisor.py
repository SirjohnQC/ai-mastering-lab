"""FRANKENSTEM: cautious local stem measurements and explainable FX advice.

No generative-source detection, objective 'quality score' or silent FX approval.
Analyse short windows distributed through each WAV, with bounded RAM usage.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
import soundfile as sf
from .auto_mix_candidates import _group
from .stem_saturation import SAFE_DEFAULTS

WINDOW_SECONDS = 1.5
WINDOW_COUNT = 5


def inspect_stem_for_fx(path, *, group=None):
    source=Path(path).resolve(strict=True)
    with sf.SoundFile(str(source)) as wav:
        if wav.channels not in (1,2) or wav.samplerate < 16000 or wav.frames < 512:
            raise ValueError('Stem must be a nonempty mono/stereo WAV >=16 kHz.')
        n=min(int(wav.samplerate*WINDOW_SECONDS), wav.frames)
        positions=[round((wav.frames-n)*i/max(1,WINDOW_COUNT-1))
                   for i in range(WINDOW_COUNT)]
        metrics=[]
        for pos in positions:
            wav.seek(pos)
            data=wav.read(n,dtype='float64',always_2d=True)
            if not np.isfinite(data).all():
                raise ValueError('Non-finite samples: saturation not recommended.')
            peak=float(np.max(np.abs(data)))
            rms=float(np.sqrt(np.mean(data**2)))
            if rms < 1e-5:
                continue
            mono=data.mean(axis=1)
            segment=mono[:min(32768,len(mono))]
            window=np.hanning(len(segment))
            power=np.abs(np.fft.rfft(segment*window))**2
            freq=np.fft.rfftfreq(len(segment),1/wav.samplerate)
            total=float(np.sum(power))
            high=float(np.sum(power[freq>=8000]))/total if total>1e-20 else 0.
            metrics.append({'rms':rms,'peak':peak,
                'crest_db':20*math.log10(max(peak,1e-10)/rms),
                'high_ratio':high,
                'near_clip':int(np.count_nonzero(np.abs(data)>=0.995))})
    category=group or _group({'file':str(source)})
    if category not in SAFE_DEFAULTS: category='other'
    if not metrics:
        return {'file':str(source),'group':category,'decision':'bypass',
                'reason':'Stem is effectively silent in sampled windows.',
                'metrics':{'sampled_windows':0},'suggestion':None}
    peak=max(x['peak'] for x in metrics)
    crest=float(np.median([x['crest_db'] for x in metrics]))
    high=float(np.median([x['high_ratio'] for x in metrics]))
    clips=sum(x['near_clip'] for x in metrics)
    stats={'sampled_windows':len(metrics),
           'sampled_peak_dbfs':round(20*math.log10(max(peak,1e-10)),2),
           'sampled_crest_db':round(crest,2),
           'sampled_high_frequency_ratio':round(high,4),
           'near_clipped_samples_in_windows':clips}
    reasons=[]
    # Conservative rule-outs instead of spurious "AI artifact detection".
    if clips>=4 or peak>=.995:
        reasons.append('Peaks near full scale; saturation may clip. Review source.')
    if category=='drums':
        reasons.append('Drums/cymbals: preserve transients by default.')
    if high>.20 and category in ('vocals','drums','other'):
        reasons.append('High-frequency energy: saturation may worsen harshness.')
    if crest<4.0:
        reasons.append('Very low sampled crest factor; additional saturation may flatten dynamics.')
    if reasons:
        return {'file':str(source),'group':category,'decision':'bypass',
                'reason':' '.join(reasons),'metrics':stats,'suggestion':None}
    if category in ('vocals','bass'):
        preset=SAFE_DEFAULTS[category]
        return {'file':str(source),'group':category,'decision':'audition',
                'reason':('Optional harmonic texture to audition; measurements '
                          'cannot establish that saturation will improve this stem.'),
                'metrics':stats,
                'suggestion':{'style':preset['style'],'drive':preset['drive'],
                              'mix':preset['mix']}}
    return {'file':str(source),'group':category,'decision':'bypass',
            'reason':'No strong reason for automatic saturation; you can audition manually.',
            'metrics':stats,'suggestion':None}


def inspect_config_for_fx(config):
    """Return per-track advice, not a processing authorization."""
    return [inspect_stem_for_fx(row['file'],group=_group(row))
            for row in config.get('tracks',[])]
