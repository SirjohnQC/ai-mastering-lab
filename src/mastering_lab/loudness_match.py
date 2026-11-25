"""Non-destructive loudness matching for Auto Mix A/B/C playback.

BS.1770 integrated loudness via pyloudnorm, measured from the actual files.
Reference is the quietest valid mix, so matching normally attenuates only.
This does NOT overwrite or normalize the exported WAVs.
"""
from __future__ import annotations
from pathlib import Path
import math
import numpy as np
import soundfile as sf


def measure_lufs(path: str | Path) -> dict:
    try:
        import pyloudnorm as pyln
    except ImportError as exc:
        raise RuntimeError('Mesure LUFS absente. Installe: python -m pip install pyloudnorm') from exc
    with sf.SoundFile(str(path)) as f:
        rate, channels, frames = f.samplerate, f.channels, len(f)
        if channels not in (1, 2) or rate < 8000:
            raise ValueError(f'Format audio non pris en charge : {path}')
        if frames < round(rate * 0.5):
            raise ValueError(f'Fichier trop court pour une mesure LUFS fiable : {path}')
        # Read one mix at a time; avoids keeping all three WAVs in memory.
        data = f.read(dtype='float32', always_2d=True)
    if not np.all(np.isfinite(data)):
        raise ValueError(f'Fichier contenant des valeurs audio invalides : {path}')
    meter = pyln.Meter(rate, block_size=0.4)
    loudness = float(meter.integrated_loudness(data))
    peak = float(np.max(np.abs(data)))
    if not math.isfinite(loudness) or loudness < -95:
        raise ValueError(f'Silence ou loudness non mesurable : {path}')
    return {'lufs_i': round(loudness, 3), 'sample_peak': peak, 'frames': frames, 'rate': rate}


def matching_gains(stats: dict, *, max_attenuation_db: float = 12.0) -> dict:
    """Compare relative to quietest mix; never boost; avoid mismatched sample-peak clipping.

    Returns per-variant scalar playback gain. If a loudness mismatch is > max attenuation,
    fail explicitly instead of suggesting the variants are adequately matched.
    """
    if len(stats) != 3 or any(not isinstance(v, dict) for v in stats.values()):
        raise ValueError('Trois mixes valides sont nécessaires.')
    levels = [float(x['lufs_i']) for x in stats.values()]
    if any(not math.isfinite(x) for x in levels):
        raise ValueError('Mesures LUFS invalides.')
    target = min(levels)
    if max(levels) - target > max_attenuation_db:
        raise ValueError('Écart LUFS trop important pour une comparaison sûre.')
    result = {}
    for key, data in stats.items():
        delta_db = target - float(data['lufs_i'])
        result[key] = float(10 ** (delta_db / 20))
    return result


def match_files(paths: dict) -> dict:
    if len(paths) != 3:
        raise ValueError('Trois chemins WAV sont nécessaires.')
    stats = {key: measure_lufs(path) for key, path in paths.items()}
    gains = matching_gains(stats)
    return {'measurements': stats, 'gains': gains,
            'target_lufs': min(v['lufs_i'] for v in stats.values())}
