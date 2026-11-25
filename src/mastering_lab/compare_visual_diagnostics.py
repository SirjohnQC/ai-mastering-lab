"""Read-only diagnostics for the nine Auto Studio WAV files.

Measured waveform envelopes use a fixed full-scale amplitude, not per-file
normalization. RMS differences are NOT plugin gain reduction. No user WAV is
modified, moved or written to the repository.
"""
from __future__ import annotations

from pathlib import Path

from .compression_diagnostics import wav_profile, compare_wav_content
from .transient_guard import compare_windows
import numpy as np
import soundfile as sf


def waveform_envelope(path, max_points=1000):
    """Fixed full-scale min/max envelope; streaming, no Qt dependency."""
    with sf.SoundFile(str(path)) as audio:
        length = len(audio)
        if length <= 0:
            return np.empty((0, 2), dtype=np.float32)
        bin_size = max(1, int(np.ceil(length / max_points)))
        mins, maxs = [], []
        while True:
            data = audio.read(frames=bin_size, dtype='float32', always_2d=True)
            if len(data) == 0:
                break
            if not np.isfinite(data).all():
                raise ValueError('Non-finite sample in waveform')
            mins.append(float(np.clip(np.min(data), -1, 1)))
            maxs.append(float(np.clip(np.max(data), -1, 1)))
        return np.stack((mins, maxs), axis=1).astype(np.float32)

MIXES = ('balanced', 'vocal-focus', 'punchy')
COMPRESSIONS = ('original', 'gentle', 'firm')


def measure_combinations(files: dict[tuple[str, str], Path]) -> dict:
    """Stream nine WAVs and compare each processed copy against its original."""
    if set(files) != {(m, c) for m in MIXES for c in COMPRESSIONS}:
        raise ValueError('Nine distinct mix/compression slots are required.')
    profiles = {}
    envelopes = {}
    results = {}
    for mix in MIXES:
        for comp in COMPRESSIONS:
            key = (mix, comp)
            path = Path(files[key]).resolve(strict=True)
            profile = wav_profile(path, bins=480)
            wave = waveform_envelope(path, max_points=1000)
            if wave is None or len(wave) == 0:
                raise ValueError('Waveform unavailable: ' + str(path))
            profiles[key] = profile
            envelopes[f'{mix}/{comp}'] = wave.tolist()
            results[f'{mix}/{comp}'] = {
                'rms_dbfs': profile['rms_dbfs'],
                'sample_peak_dbfs': profile['sample_peak_dbfs'],
                'crest_db': profile['crest_db'],
                'path': str(path),
            }

    warnings = []
    for mix in MIXES:
        original = profiles[(mix, 'original')]
        for comp in ('gentle', 'firm'):
            key = f'{mix}/{comp}'
            variant = profiles[(mix, comp)]
            if (original['sample_rate'], original['channels']) != (
                    variant['sample_rate'], variant['channels']):
                warnings.append(key + ': sample rate/channel mismatch')
                continue
            delta = compare_wav_content(
                files[(mix, 'original')], files[(mix, comp)],
                frames=original['frames'],
            )
            windows = compare_windows(
                files[(mix, 'original')], files[(mix, comp)],
                frames=original['frames'])
            results[key]['window_analysis'] = windows
            if windows.get('overcompression_warning'):
                warnings.append(key + ': strong loud-vs-quiet reduction in PCM windows; review by ear')
            results[key].update({
                'same_samples_as_original': delta['same_samples'],
                'rms_delta_db': delta['rms_delta_db'],
                'null_difference_rms_dbfs': delta['null_difference_rms_dbfs'],
                'max_absolute_sample_difference': delta['max_absolute_sample_difference'],
            })
            if delta['same_samples']:
                warnings.append(key + ': EXACT same samples as Original; inspect VST routing or bypass')
    return {'schema_version': 2, 'envelopes': envelopes, 'metrics': results,
            'warnings': warnings, 'note': 'Measured source WAV files; not FabFilter gain-reduction telemetry.'}
