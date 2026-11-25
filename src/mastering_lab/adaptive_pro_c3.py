"""Conservative song-aware Pro-C 3 plan using ONLY previously probed grid points.

No guessed normalized values, plugin calls or writes here. Plan is heuristic;
JUCE readback and waveform checks must still succeed before audition.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

from .pro_c3_parameter_validation import prepare_discrete_scenario

BLOCK = 65536
PLAN_VERSION = 1


def source_dynamics(source: Path) -> dict:
    """Streaming input analysis; compute peak, RMS and crest from stereo PCM."""
    source = Path(source).resolve(strict=True)
    with sf.SoundFile(str(source)) as stream:
        if stream.channels != 2 or stream.samplerate != 48000 or stream.frames <= 0:
            raise ValueError('Song-aware plan requires nonempty stereo 48 kHz WAV.')
        sum_sq, n, peak = 0.0, 0, 0.0
        while True:
            samples = stream.read(BLOCK, dtype='float32', always_2d=True)
            if not len(samples):
                break
            if not np.isfinite(samples).all():
                raise ValueError('Source contains non-finite PCM samples.')
            sum_sq += float(np.sum(samples.astype('float64') ** 2))
            n += samples.size
            peak = max(peak, float(np.max(np.abs(samples))))
    if n == 0 or peak <= 1e-9:
        raise ValueError('Cannot plan compression for silent source.')
    rms = math.sqrt(sum_sq / n)
    return {'rms_dbfs':round(20*math.log10(rms),3),
            'peak_dbfs':round(20*math.log10(peak),3),
            'crest_db':round(20*math.log10(peak/rms),3)}


def plan_scenarios(measurements: dict) -> dict:
    """Select a finite set of confirmed normalized mapping points.

    Gentler threshold for hot, dense mix; lower threshold for quieter,
    transient mixes. Firm backs off its threshold on already-dense material.
    Attack/release are unchanged. No interpolated VST parameter values.
    """
    peak = measurements.get('peak_dbfs')
    crest = measurements.get('crest_db')
    if not isinstance(peak, (float,int)) or not isinstance(crest, (float,int)):
        raise ValueError('Missing input measurements.')
    if isinstance(peak,bool) or isinstance(crest,bool) or not math.isfinite(peak) or not math.isfinite(crest):
        raise ValueError('Invalid input measurements.')
    if peak > 1.0 or crest < 0 or crest > 60:
        raise ValueError('Input out of supported dynamic range.')
    stronger_gentle = peak <= -8 and crest >= 11
    back_off_firm = crest <= 9
    gentle = {'threshold':0.70 if stronger_gentle else 0.85,
              'ratio':0.30,'attack':0.30,'release':0.30}
    firm = {'threshold':0.85 if back_off_firm else 0.70,
            'ratio':0.70,'attack':0.30,'release':0.30}
    return {'version':PLAN_VERSION, 'measurements':measurements,
            'scenarios':{'gentle':gentle,'firm':firm},
            'method':'song-aware-discrete-verified-grid',
            'note':'Heuristic parameter plan. Does not infer Pro-C 3 gain reduction.'}


def prepare_adaptive(grid: dict, source: Path):
    """Return plan + safely validated scenario tuples for the JUCE host."""
    plan = plan_scenarios(source_dynamics(source))
    prepared = {}
    for name, values in plan['scenarios'].items():
        prepared[name] = prepare_discrete_scenario(grid, values)
    return plan, prepared
