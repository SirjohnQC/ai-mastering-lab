"""Non-destructive diagnostics for Auto Studio 3x3 mix/compression comparison.

No Qt, JUCE or Ollama dependency. All metrics are measured from WAV samples.
Do not equate changes in RMS with compressor gain reduction (GR).
"""
from __future__ import annotations

import argparse
import csv
import json
import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

MIXES = ('balanced', 'vocal-focus', 'punchy')
COMPRESSIONS = ('original', 'gentle', 'firm')
MAX_CHANNELS = 2
BLOCK = 65536


def _db(x: float) -> float | None:
    return round(20 * math.log10(x), 3) if x > 0 else None


def _path_in(base: Path, path: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def read_cached_sources(root: Path) -> dict[tuple[str, str], Path]:
    """Only WAVs from a valid last-session cache; originals can be in preview folder."""
    root = Path(root).resolve()
    manifest = root / 'settings' / 'pro_c3_unified_cache.json'
    document = json.loads(manifest.read_text(encoding='utf-8'))
    result = document['result']
    if result.get('status') != 'ready' or set(result.get('mixes', {})) != set(MIXES):
        raise ValueError('Manifest incomplete or not ready.')
    allowed = (root / 'settings' / 'pro_c3_song_previews').resolve()
    found: dict[tuple[str, str], Path] = {}
    for mix in MIXES:
        data = result['mixes'][mix]
        if set(data.get('paths', {})) != set(COMPRESSIONS):
            raise ValueError(f'Incomplete compression paths for {mix}.')
        for comp in COMPRESSIONS:
            path = Path(data['paths'][comp]).resolve()
            if not path.is_file() or path.suffix.lower() != '.wav':
                raise FileNotFoundError(str(path))
            # Diagnostics must never read arbitrary files from injected manifest.
            if not _path_in(allowed, path):
                raise ValueError(f'Cached path outside preview directory: {path}')
            found[mix, comp] = path
    return found


def wav_profile(path: Path, *, bins: int = 720, max_seconds: int = 600) -> dict[str, Any]:
    """Stream entire musical signal; envelope contains per-bin absolute peaks.

    The JUCE output may have an additional short tail, so callers can limit
    comparison to the original frame count with the `frames` argument separately.
    """
    path = Path(path)
    with sf.SoundFile(str(path), 'r') as wav:
        sr, channels, frames = wav.samplerate, wav.channels, wav.frames
        if channels != 2 or not 8000 <= sr <= 192000:
            raise ValueError(f'Invalid stereo source: {path.name}')
        if frames == 0 or frames > sr * max_seconds + sr:
            raise ValueError('Invalid or excessively long audio source.')
        if bins < 20 or bins > 5000:
            raise ValueError('Invalid waveform resolution.')
        envelope = np.zeros(bins, dtype='float64')
        squared = 0.0
        total_samples = 0
        peak = 0.0
        silent_frames = 0
        cursor = 0
        while True:
            samples = wav.read(BLOCK, dtype='float32', always_2d=True)
            if samples.size == 0:
                break
            if not np.isfinite(samples).all():
                raise ValueError('Audio contains NaN/Inf')
            absolute = np.max(np.abs(samples), axis=1)
            peak = max(peak, float(np.max(absolute)))
            silent_frames += int(np.count_nonzero(absolute < 10**(-70/20)))
            squared += float(np.sum(samples.astype('float64') ** 2))
            total_samples += samples.size
            # One envelope per file; bin edges and frame count are deterministic.
            index = np.minimum(bins - 1, ((cursor + np.arange(len(samples), dtype=np.int64)) * bins) // frames)
            np.maximum.at(envelope, index, absolute)
            cursor += len(samples)
    rms = math.sqrt(squared / total_samples) if total_samples else 0.0
    return {
        'path': str(path), 'frames': frames, 'channels': channels, 'sample_rate': sr,
        'duration_seconds': round(frames/sr, 4),
        'rms_dbfs': _db(rms), 'sample_peak_dbfs': _db(peak),
        'crest_db': round(20 * math.log10(peak / rms), 3) if peak > 0 and rms > 0 else None,
        'silent_frames_below_minus70db': silent_frames,
        'envelope': [round(float(x), 6) for x in envelope],
    }


def compare_wav_content(a_path: Path, b_path: Path, *, frames: int) -> dict[str, Any]:
    """Aligned sample-based null comparison of musical frames, excluding JUCE tail.

    Correlation is informational. Silence/very quiet regions are not counted as
    evidence that a compressor is bypassed. Difference is not gain reduction.
    """
    with sf.SoundFile(str(a_path)) as a, sf.SoundFile(str(b_path)) as b:
        if a.channels != b.channels or a.samplerate != b.samplerate or a.channels != 2:
            raise ValueError('Cannot compare incompatible WAV shape.')
        if frames > min(a.frames, b.frames):
            raise ValueError('Required musical frames missing.')
        sum_delta_sq = sum_a_sq = sum_b_sq = cross = 0.0
        max_delta = 0.0
        remaining = frames
        while remaining:
            take = min(remaining, BLOCK)
            av = a.read(take, dtype='float32', always_2d=True).astype('float64')
            bv = b.read(take, dtype='float32', always_2d=True).astype('float64')
            if len(av) != take or len(bv) != take or not np.isfinite(av).all() or not np.isfinite(bv).all():
                raise ValueError('Invalid WAV content.')
            delta = bv - av
            sum_delta_sq += float(np.sum(delta * delta))
            sum_a_sq += float(np.sum(av * av))
            sum_b_sq += float(np.sum(bv * bv))
            cross += float(np.sum(av * bv))
            max_delta = max(max_delta, float(np.max(np.abs(delta))))
            remaining -= take
    total_samples = frames * 2
    delta_rms = math.sqrt(sum_delta_sq / total_samples)
    correlation = cross / math.sqrt(sum_a_sq * sum_b_sq) if sum_a_sq > 0 and sum_b_sq > 0 else None
    a_rms = math.sqrt(sum_a_sq / total_samples)
    b_rms = math.sqrt(sum_b_sq / total_samples)
    return {
        'same_samples': max_delta == 0,
        'null_difference_rms_dbfs': _db(delta_rms),
        'max_absolute_sample_difference': round(max_delta, 7),
        'rms_delta_db': round(20 * math.log10(b_rms / a_rms), 3) if a_rms > 0 and b_rms > 0 else None,
        'aligned_sample_correlation': round(correlation, 7) if correlation is not None else None,
        'comparison_frames': frames,
    }


def analyze_cache(root: Path, *, bins: int = 720) -> dict[str, Any]:
    sources = read_cached_sources(root)
    profiles = {f'{mix}/{comp}': wav_profile(path, bins=bins) for (mix,comp),path in sources.items()}
    diffs: dict[str, Any] = {}
    warnings = []
    for mix in MIXES:
        original = profiles[f'{mix}/original']
        for comp in ('gentle', 'firm'):
            variant = profiles[f'{mix}/{comp}']
            if original['sample_rate'] != variant['sample_rate'] or original['channels'] != variant['channels']:
                warnings.append(f'{mix}/{comp}: shape mismatch')
                continue
            diff = compare_wav_content(sources[mix,'original'], sources[mix,comp], frames=original['frames'])
            diffs[f'{mix}/{comp}'] = diff
            if diff['same_samples']:
                warnings.append(f'{mix}/{comp} is EXACTLY identical to Original: investigate plugin bypass or routing')
            elif diff['rms_delta_db'] is not None and abs(diff['rms_delta_db']) < 0.1:
                warnings.append(f'{mix}/{comp}: small overall RMS difference; audible effect may be subtle')
    return {'schema_version':1, 'kind':'unified_compression_diagnostics', 'metrics':'Measured WAV sample data, not LUFS or plugin gain-reduction',
            'profiles':profiles, 'differences_from_original':diffs, 'warnings':warnings}


def save_reports(root: Path, result: dict[str, Any], *, output_dir: Path | None = None):
    root = Path(root).resolve()
    folder = Path(output_dir).resolve() if output_dir else root / 'settings' / 'pro_c3_diagnostics'
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / 'latest.json'
    temp = json_path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(json_path)
    csv_path = folder / 'latest.csv'
    with csv_path.open('w', newline='', encoding='utf-8-sig') as fh:
        fields = ['combination','rms_dbfs','sample_peak_dbfs','crest_db','rms_delta_db','null_difference_rms_dbfs','identical_to_original']
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for key, p in result['profiles'].items():
            d = result['differences_from_original'].get(key, {})
            writer.writerow({'combination':key, 'rms_dbfs':p['rms_dbfs'], 'sample_peak_dbfs':p['sample_peak_dbfs'],
                            'crest_db':p['crest_db'], 'rms_delta_db':d.get('rms_delta_db'),
                            'null_difference_rms_dbfs':d.get('null_difference_rms_dbfs'),
                            'identical_to_original':d.get('same_samples')})
    return json_path, csv_path


def main():
    p = argparse.ArgumentParser(description='Read-only diagnostics for Auto Studio v0.23.1 cache')
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--bins', type=int, default=720)
    args = p.parse_args()
    result = analyze_cache(args.root, bins=args.bins)
    jp,cp = save_reports(args.root, result)
    print('Audio analysis complete. No WAV modified.')
    for mix in MIXES:
        for comp in ('gentle','firm'):
            key = f'{mix}/{comp}'
            d = result['differences_from_original'].get(key)
            if d:
                print(f'{key}: identical={d["same_samples"]}; ΔRMS={d["rms_delta_db"]} dB; null RMS={d["null_difference_rms_dbfs"]} dBFS')
    for warning in result['warnings']:
        print('WARNING:', warning)
    print('JSON:', jp)
    print('CSV:', cp)


if __name__ == '__main__':
    main()
