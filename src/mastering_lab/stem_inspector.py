"""Conservative, explainable stem diagnostics. NOT an AI-origin or sound-quality classifier.

All analysis is read-only. Time ranges are suggestions for human review.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import math
import subprocess
import tempfile
from datetime import datetime, timezone

import numpy as np
import soundfile as sf

EXTENSIONS = {'.wav', '.flac', '.aiff', '.aif', '.mp3'}
VALID_CATEGORIES = ('vocals', 'guitars', 'drums', 'bass', 'other')


def classify_stem(path: Path) -> str:
    name = path.stem.lower()
    if any(x in name for x in ('voc', 'sing', 'leadvox', 'backingvox')):
        return 'vocals'
    if any(x in name for x in ('guitar', 'gtr', 'acoustic', 'electric')):
        return 'guitars'
    if any(x in name for x in ('drum', 'percussion', 'cymbal', 'snare', 'kick')):
        return 'drums'
    if 'bass' in name:
        return 'bass'
    return 'other'


def discover_stems(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in EXTENSIONS and
                   not any(part.lower() in ('output', 'cache') for part in p.relative_to(folder).parts)),
                  key=lambda p: p.as_posix().casefold())


def default_stem_folder(root: Path, source: Path | None) -> Path:
    base = root / 'sound' / 'stems'
    if source:
        exact = base / source.stem
        if exact.is_dir():
            return exact
    return base


def _convert_mp3(path: Path, dest: Path) -> Path:
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(path),
               '-vn', '-c:a', 'pcm_f32le', str(dest)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    except FileNotFoundError as exc:
        raise RuntimeError('FFmpeg required to decode MP3 stems. Install FFmpeg and check PATH.') from exc
    if result.returncode or not dest.is_file() or dest.stat().st_size < 44:
        raise RuntimeError(f'MP3 decode failed: {result.stderr[-400:]}')
    return dest


def _features(data: np.ndarray, rate: int) -> dict:
    """Compute features for one analysis window, including relative HF energy."""
    data = np.asarray(data, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    finite = np.isfinite(data).all()
    if not finite:
        data = np.nan_to_num(data)
    mono = data.mean(axis=1)
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    rms = float(np.sqrt(np.mean(data * data))) if data.size else 0.0
    crest = 20 * math.log10(max(peak, 1e-12) / max(rms, 1e-12))
    # Silence alone isn't a defect. It is reported as a quiet passage only.
    if len(mono) > 512:
        w = np.hanning(len(mono))
        spectrum = np.abs(np.fft.rfft(mono * w)) ** 2
        frequencies = np.fft.rfftfreq(len(mono), 1 / rate)
        total = float(np.sum(spectrum))
        hf = float(np.sum(spectrum[frequencies >= 10000])) / total if total > 1e-20 else 0.0
    else:
        hf = 0.0
    return {'rms_dbfs': round(20 * math.log10(max(rms, 1e-12)), 2),
            'peak_dbfs': round(20 * math.log10(max(peak, 1e-12)), 2),
            'crest_db': round(crest, 2), 'hf_ratio_above_10khz': round(hf, 5),
            'near_clipped_samples': int(np.count_nonzero(np.abs(data) >= 0.999)),
            'nonfinite_audio': not finite}


def inspect_audio_file(path: Path, window_seconds: float = 2.0) -> dict:
    """Window-by-window detection; preserves timestamps and avoids modifying source."""
    with tempfile.TemporaryDirectory(prefix='aml-stems-') as td:
        audio = path
        if path.suffix.lower() == '.mp3':
            audio = _convert_mp3(path, Path(td) / 'decoded.wav')
        with sf.SoundFile(str(audio), mode='r') as f:
            rate = f.samplerate
            frames = len(f)
            channels = f.channels
            if rate <= 0 or frames <= 0:
                raise ValueError('Audio is empty or has an invalid sample rate')
            n = max(512, round(rate * window_seconds))
            windows = []
            for offset in range(0, frames, n):
                chunk = f.read(min(n, frames - offset), dtype='float32', always_2d=True)
                if chunk.size == 0:
                    break
                feat = _features(chunk, rate)
                feat['start_ms'] = round(offset * 1000 / rate)
                feat['end_ms'] = round((offset + len(chunk)) * 1000 / rate)
                windows.append(feat)
            issues = []
            if windows:
                # Contextual comparisons are less brittle than absolute energy thresholds.
                active = [x['rms_dbfs'] for x in windows if x['rms_dbfs'] > -70]
                median = float(np.median(active)) if active else -90.0
                for i, w in enumerate(windows):
                    reasons=[]
                    if w['nonfinite_audio']:
                        reasons.append(('invalid_samples', 'Non-finite sample(s) detected', 'high'))
                    if w['near_clipped_samples'] >= 5:
                        reasons.append(('possible_clipping', f"{w['near_clipped_samples']} samples near full scale", 'medium'))
                    if median > -45 and w['rms_dbfs'] < median - 36 and w['rms_dbfs'] < -52:
                        reasons.append(('possible_dropout', f"Quiet segment ({w['rms_dbfs']} dBFS; track median {median:.1f} dBFS). May be intentional.", 'low'))
                    if rate >= 24000 and w['hf_ratio_above_10khz'] > 0.22 and w['rms_dbfs'] > -55:
                        reasons.append(('high_frequency_energy', f"{100*w['hf_ratio_above_10khz']:.1f}% energy above 10 kHz; review, not automatically an artifact", 'low'))
                    for label, explanation, severity in reasons:
                        issues.append({'start_ms': w['start_ms'], 'end_ms': w['end_ms'],
                                       'issue': label, 'severity': severity, 'reason': explanation,
                                       'status': 'needs_human_review', 'features': w})
            return {'file': str(path.resolve()), 'category': classify_stem(path),
                    'sample_rate': rate, 'channels': channels,
                    'duration_ms': round(frames * 1000 / rate), 'windows': windows, 'suspicions': issues}


def inspect_folder(root: Path, folder: Path, source: Path | None = None) -> dict:
    stems = discover_stems(folder)
    if not stems:
        raise ValueError(f'No supported audio files (.wav/.flac/.aiff/.mp3) in: {folder}')
    rows=[]; errors=[]
    for file in stems:
        try:
            rows.append(inspect_audio_file(file))
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            errors.append({'file': str(file), 'error': str(exc)})
    return {'schema_version':1,'created_utc':datetime.now(timezone.utc).isoformat(),
            'source':str(source.resolve()) if source else None, 'stem_directory':str(folder.resolve()),
            'method':'deterministic_window_heuristics_not_AI',
            'limitations':'Flags are review suggestions, NOT proof of AI generation or objectively bad sound.',
            'stems':rows,'errors':errors}


def save_report(root: Path, report: dict, source: Path | None = None) -> Path:
    slug = source.stem if source else 'unassigned'
    digest = hashlib.sha256((str(source.resolve()) if source else report['stem_directory']).encode()).hexdigest()[:10]
    output = root / 'sound' / 'output' / 'stem_inspector' / f'{slug}-{digest}' / 'report.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return output
