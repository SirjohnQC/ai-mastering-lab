"""Reference-guided, conservative tonal comparison (not a complete mastering engine).

Input: stereo uncompressed WAV. Measurement uses energy-weighted Welch PSD.
Report differences relative to mean level in 250 Hz–8 kHz, so simple loudness
differences don't produce mistaken EQ changes. Silence/low-energy bands are ignored.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import numpy as np
import soundfile as sf
from scipy.signal import welch

# Broad-band correction targets, 1-octave centers. Avoid the extreme sub and air bands.
CENTERS = (125., 250., 500., 1000., 2000., 4000., 8000.)
BANDS = tuple((c / np.sqrt(2), c * np.sqrt(2)) for c in CENTERS)
EPS = 1e-15

@dataclass
class Analysis:
    file: str
    sample_rate: int
    duration_seconds: float
    rms_dbfs: float
    peak_dbfs: float
    band_db: list[float]
    spectral_shape_db: list[float]

def analyze(path: str | Path) -> Analysis:
    path = Path(path)
    data, sr = sf.read(str(path), dtype='float32', always_2d=True)
    if len(data) < 4096 or sr < 16000 or sr > 192000 or data.shape[1] not in (1, 2):
        raise ValueError('Requires WAV audio >=4096 frames, mono/stereo, 16–192 kHz')
    if not np.all(np.isfinite(data)):
        raise ValueError('Audio contains non-finite samples')
    peak = float(np.max(np.abs(data)))
    rms = float(np.sqrt(np.mean(np.square(data.astype(np.float64)))))
    if rms < 1e-7:
        raise ValueError('Input is silent/too quiet to compare')
    # Mean L/R power avoids stereo cancellation from collapsing out-of-phase material.
    nperseg = min(8192, len(data))
    freq, pxx = welch(data, fs=sr, axis=0, nperseg=nperseg,
                      noverlap=nperseg//2, scaling='density')
    pxx = np.mean(pxx, axis=1)
    powers = []
    for lo, hi in BANDS:
        mask = (freq >= lo) & (freq < hi)
        if not mask.any():
            raise ValueError('Sample rate insufficient for spectral analysis')
        powers.append(float(np.sum(pxx[mask]) * (freq[1] - freq[0])))
    db = 10 * np.log10(np.maximum(powers, EPS))
    # Remove average midrange spectral offset. This is relative tonal shape, not absolute loudness.
    anchor = float(np.mean(db[1:6]))
    shape = db - anchor
    return Analysis(str(path), int(sr), round(len(data) / sr, 4),
                    round(20 * np.log10(max(rms, EPS)), 3),
                    round(20 * np.log10(max(peak, EPS)), 3),
                    [round(float(v), 3) for v in db],
                    [round(float(v), 3) for v in shape])

def suggest(source: Analysis, reference: Analysis, strength: float = .55,
            max_gain_db: float = 2.0) -> list[dict]:
    if not 0 < strength <= 1 or not 0 < max_gain_db <= 6:
        raise ValueError('strength must be (0,1], max_gain_db must be (0,6]')
    differences = np.array(reference.spectral_shape_db) - np.array(source.spectral_shape_db)
    # Dense songs with different arrangements may need entirely different tonal balance.
    # Smooth peaks and valleys and limit changes so the reference doesn't overpower identity.
    smoothed = np.convolve(np.pad(differences, (1,1), mode='edge'),
                           np.array([.25,.50,.25]), mode='valid')
    gains = np.clip(smoothed * strength, -max_gain_db, max_gain_db)
    return [dict(center_hz=c, raw_difference_db=round(float(d),2),
                 recommended_gain_db=round(float(g),2), q=0.7)
            for c,d,g in zip(CENTERS, differences, gains)]

def report(source_path: str | Path, reference_path: str | Path,
           strength: float = .55, max_gain_db: float = 2.0) -> dict:
    s, r = analyze(source_path), analyze(reference_path)
    return {'source':asdict(s), 'reference':asdict(r),
            'suggestions':suggest(s,r,strength,max_gain_db),
            'method':'Welch octave-band spectral shape comparison; level-independent',
            'warning':'Reference matching is advisory. Different instrumentation/arrangement can make tonal matching inappropriate; listen before accepting.'}

def save_report(payload: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
