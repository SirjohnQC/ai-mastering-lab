"""Local reference-library feature extraction (no model training, no cloud upload).

Features are level-independent relative spectral shares plus measured RMS and crest.
This does not measure perceived tonal balance, LUFS, or artistic quality.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import subprocess
import shutil
from pathlib import Path

BANDS_HZ = ((20, 60), (60, 120), (120, 250), (250, 500),
            (500, 2000), (2000, 5000), (5000, 10000), (10000, 20000))
SCHEMA = 1


def _extract_pcm_features(filename, *, max_seconds=75.0):
    """Read up to 75 seconds throughout the recording in bounded chunks.

    Band fractions come from FFT power on 8192-sample blocks, with DC ignored.
    Whole-file dynamics are *not* claimed; this is a sampled preview.
    """
    import numpy as np
    import soundfile as sf

    path = Path(filename).resolve()
    with sf.SoundFile(str(path)) as wav:
        if wav.channels not in (1, 2) or wav.samplerate < 22050 or len(wav) < 8192:
            raise ValueError('Référence audio mono/stéréo de durée suffisante requise (≥ 22050 Hz).')
        rate, duration = int(wav.samplerate), len(wav)/wav.samplerate
        chunk = 8192
        total_windows = min(96, max(1, int(max_seconds * rate // chunk)))
        offsets = np.linspace(0, max(0, len(wav)-chunk), total_windows, dtype='int64')
        weights = np.zeros(len(BANDS_HZ), dtype='float64')
        peak, energy, count = 0.0, 0.0, 0
        freq = np.fft.rfftfreq(chunk, d=1/rate)
        window = np.hanning(chunk)
        masks = [(freq >= lo) & (freq < hi) for lo, hi in BANDS_HZ]
        for offset in offsets:
            wav.seek(int(offset))
            frames = wav.read(chunk, dtype='float64', always_2d=True)
            if len(frames) != chunk or not np.isfinite(frames).all():
                raise ValueError(f'Référence audio invalide : {path.name}')
            peak = max(peak, float(np.abs(frames).max()))
            energy += float(np.square(frames).sum())
            count += frames.size
            mono = frames.mean(axis=1)
            power = np.abs(np.fft.rfft(mono * window)) ** 2
            for i, mask in enumerate(masks):
                weights[i] += float(power[mask].sum())
    total = float(weights.sum())
    if total <= 1e-18:
        raise ValueError('Référence silencieuse ou sans énergie spectrale exploitable.')
    rms = math.sqrt(energy/count)
    if rms <= 1e-9:
        raise ValueError('Référence silencieuse.')
    return {
        'source': str(path), 'sample_rate': rate, 'duration_seconds': round(duration, 2),
        'sampled_seconds': round(total_windows*chunk/rate, 2),
        'sample_peak_dbfs': round(20*math.log10(max(peak, 1e-12)), 2),
        'rms_dbfs': round(20*math.log10(rms), 2),
        'crest_db': round(20*math.log10(max(peak, 1e-12)/rms), 2),
        'spectral_shares': [round(float(x/total), 6) for x in weights],
    }


def extract_features(filename, *, max_seconds=75.0):
    """Analyze WAV/FLAC/MP3; if libsndfile cannot read MP3, decode a bounded preview.

    The temporary WAV is deleted after analysis; original files are never changed.
    """
    source = Path(filename).resolve()
    if source.suffix.casefold() not in {'.wav', '.flac', '.mp3'}:
        raise ValueError('Format non pris en charge : WAV, FLAC ou MP3 requis.')
    try:
        return _extract_pcm_features(source, max_seconds=max_seconds)
    except Exception as original_error:
        if source.suffix.casefold() != '.mp3':
            raise
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            raise RuntimeError('Décodage MP3 impossible. Installe FFmpeg et ajoute-le au PATH.') from original_error
        with tempfile.TemporaryDirectory(prefix='aml-ref-mp3-') as td:
            decoded = Path(td) / 'decoded.wav'
            args = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                    '-i', str(source), '-map', '0:a:0', '-vn', '-t', str(max(1, min(float(max_seconds), 75.0))),
                    '-ac', '2', '-c:a', 'pcm_s16le', str(decoded)]
            try:
                result = subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('Le décodage MP3 a dépassé le délai autorisé.') from exc
            if result.returncode != 0 or not decoded.is_file():
                raise RuntimeError('FFmpeg ne peut pas décoder ce MP3 : ' + (result.stderr or 'erreur inconnue')[-400:])
            features = _extract_pcm_features(decoded, max_seconds=max_seconds)
            features['source'] = str(source)
            features['duration_seconds'] = _mp3_duration_hint(source, features['duration_seconds'])
            return features


def _mp3_duration_hint(source, fallback):
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        return fallback
    try:
        result = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration',
                                 '-of', 'default=noprint_wrappers=1:nokey=1', str(source)],
                                capture_output=True, text=True, timeout=15, check=False)
        if result.returncode == 0:
            duration = float(result.stdout.strip())
            if math.isfinite(duration) and duration > 0:
                return round(duration, 2)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        pass
    return fallback


def library_path(root):
    return Path(root) / 'settings' / 'reference_learning.json'


def load_library(path):
    path = Path(path)
    if not path.exists():
        return {'schema': SCHEMA, 'active': [], 'entries': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema') != SCHEMA:
        raise ValueError('Format de la bibliothèque de références incompatible.')
    if not isinstance(data.get('entries'), list) or not isinstance(data.get('active'), list):
        raise ValueError('Bibliothèque de références invalide.')
    return data


def save_library(path, library):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement so interruption cannot leave an empty library.
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                     prefix='.references-', suffix='.tmp', delete=False) as f:
        tmp = Path(f.name)
        json.dump(library, f, ensure_ascii=False, indent=2)
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def add_reference(library, file_path, features):
    path = str(Path(file_path).resolve())
    entries = [x for x in library['entries'] if x['path'] != path]
    entries.append({'path': path, 'features': features})
    active = list(dict.fromkeys([*library.get('active', []), path]))
    return {'schema': SCHEMA, 'entries': entries, 'active': active}


def reference_context(library):
    """Simple mean profile; no claims of trained weights or generalized preferences."""
    active = set(library.get('active', []))
    entries = [x['features'] for x in library['entries']
               if x.get('path') in active and isinstance(x.get('features'), dict)]
    if not entries:
        return None
    import numpy as np
    shares = np.array([x['spectral_shares'] for x in entries], dtype='float64')
    if shares.ndim != 2 or shares.shape[1] != len(BANDS_HZ) or not np.isfinite(shares).all():
        raise ValueError('Profil de référence invalide.')
    return {
        'count': len(entries), 'bands_hz': [list(x) for x in BANDS_HZ],
        'mean_spectral_shares': [round(float(x), 6) for x in shares.mean(axis=0)],
        'median_crest_db': round(float(np.median([x['crest_db'] for x in entries])), 2),
        'limitations': 'Partial sampled FFT power and sampled crest; not full-song LUFS, true peak, or psychoacoustic match.',
    }


def load_active_context(path):
    return reference_context(load_library(path))
