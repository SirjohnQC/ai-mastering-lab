"""Safe, playback-only approximate level matching for opt-in Pro-C 3 A/B/C.

This estimates active-content RMS (not integrated LUFS). All matching is done
by attenuation in the Qt audio output: WAV samples and source files are untouched.
"""
from __future__ import annotations
import math
from pathlib import Path

import numpy as np
import soundfile as sf


BLOCK_FRAMES = 19200  # 400 ms at 48 kHz
MAX_ATTENUATION_DB = 18.0
BASE_VOLUME = 0.75


def active_rms_dbfs(path, *, source_frames, sample_rate=48000):
    """Estimate content RMS using 400 ms non-silent windows; ignore JUCE tail.

    Gate each block relative to the highest non-silent block (within 20 dB),
    with an absolute silence floor, to reduce sensitivity to silence padding.
    Return None for silent or invalid audio. Stream rather than loading a song.
    """
    with sf.SoundFile(str(path)) as stream:
        if stream.channels != 2 or stream.samplerate != sample_rate or stream.frames < source_frames:
            raise ValueError('Audio A/B/C incompatible pour comparaison de niveau.')
        energies = []
        remaining = int(source_frames)
        while remaining > 0:
            block = stream.read(min(BLOCK_FRAMES, remaining), dtype='float32', always_2d=True)
            if len(block) == 0 or not np.isfinite(block).all():
                raise ValueError('Audio invalide pour comparaison de niveau.')
            energies.append((float(np.mean(np.square(block.astype(np.float64)))), len(block)))
            remaining -= len(block)
    if not energies:
        return None
    highest = max(power for power, _ in energies)
    if highest <= 1e-12:
        return None
    gate = max(1e-10, highest * .01)
    active = [(power, count) for power, count in energies if power >= gate]
    if not active:
        return None
    total_frames = sum(count for _, count in active)
    rms_power = sum(power * count for power, count in active) / total_frames
    return round(10 * math.log10(rms_power), 3)


def build_playback_matching(paths, *, source_frames, sample_rate=48000):
    """Compute per-version attenuation only (never amplify), max 18 dB.

    No content is written. Caller should use gain_db on QAudioOutput only.
    """
    if set(paths) != {'original', 'gentle', 'firm'}:
        raise ValueError('Trois versions audio nécessaires.')
    levels = {k: active_rms_dbfs(Path(v), source_frames=source_frames, sample_rate=sample_rate)
              for k, v in paths.items()}
    if any(value is None for value in levels.values()):
        raise ValueError('Version silencieuse : égalisation d’écoute indisponible.')
    target = min(levels.values())
    raw_gains = {k: min(0.0, target - db) for k, db in levels.items()}
    gains = {k: round(max(-MAX_ATTENUATION_DB, delta), 3) for k, delta in raw_gains.items()}
    truncated = any(raw_gains[k] < -MAX_ATTENUATION_DB for k in paths)
    return {'method':'active_rms_approx', 'metric':'active-content RMS (not LUFS)',
            'status':'limited' if truncated else 'ready', 'source_frames':int(source_frames),
            'level_dbfs':levels, 'target_dbfs':round(target,3), 'gain_db':gains,
            'max_attenuation_db':MAX_ATTENUATION_DB, 'base_volume':BASE_VOLUME,
            'note':'Atténuation de lecture uniquement; niveau approximatif, pas LUFS intégré. Aucun WAV modifié.'}


def preview_volume(matching, kind, enabled):
    """Safe Qt linear amplitude multiplier, bounded [0, 1]."""
    if kind not in ('original', 'gentle', 'firm'):
        raise ValueError('Version inconnue.')
    if not enabled or not matching or matching.get('status') not in ('ready','limited'):
        return BASE_VOLUME
    db = matching['gain_db'][kind]
    if not isinstance(db, (int,float)) or not math.isfinite(db) or not -MAX_ATTENUATION_DB <= db <= 0:
        raise ValueError('Gain d’écoute non valide.')
    return max(0., min(1., BASE_VOLUME * 10 ** (db / 20)))
