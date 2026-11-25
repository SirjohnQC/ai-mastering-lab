"""Non-destructive stem mix preview; optional FabFilter Pro-Q 4 per-stem processing.

NOT a mastering/AI-artifact-repair engine. Uses checked-length tracks and conservative peak safety.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import math
import subprocess
import tempfile
import numpy as np
import soundfile as sf
from .stem_inspector import classify_stem, discover_stems

PRESETS = {
    'vocals': [(180, -0.5), (3000, 0.5)],
    'guitars': [(250, -0.6), (4000, -0.4)],
    'bass': [(120, 0.4), (700, -0.4)],
    'drums': [(250, -0.4), (6000, 0.4)],
    'other': [],
}

@dataclass(frozen=True)
class Track:
    path: Path
    gain_db: float = 0.0
    pan: float = 0.0  # -1 left to +1 right
    mute: bool = False
    eq: bool = False


def config_template(folder: Path) -> dict:
    tracks = discover_stems(folder)
    return {'schema_version': 1, 'description': 'Dry stem reconstruction by default. EQ requires explicit opt-in.',
            'tracks': [{'file': str(p.resolve()), 'category': classify_stem(p),
                        'gain_db': 0.0, 'pan': 0.0, 'mute': False, 'eq': False} for p in tracks]}


def parse_tracks(config: dict, folder: Path) -> list[Track]:
    if not isinstance(config.get('tracks'), list) or not config['tracks']:
        raise ValueError('Configuration must contain a nonempty tracks list')
    tracks = []
    for item in config['tracks']:
        path = Path(item['file']).resolve()
        if not path.is_file() or (not config.get('selection_mode') == 'files' and not path.is_relative_to(folder.resolve())):
            raise ValueError(f'Track must exist inside the chosen stem folder: {path}')
        gain, pan = float(item.get('gain_db', 0)), float(item.get('pan', 0))
        if not math.isfinite(gain) or abs(gain) > 18 or not math.isfinite(pan) or not -1 <= pan <= 1:
            raise ValueError(f'Unsafe gain or pan for {path.name}')
        tracks.append(Track(path, gain, pan, bool(item.get('mute', False)), bool(item.get('eq', False))))
    if len(set(t.path for t in tracks)) != len(tracks):
        raise ValueError('Duplicate track in configuration')
    return tracks


def decode_audio(path: Path, td: Path) -> Path:
    if path.suffix.lower() != '.mp3':
        return path
    dest = td / (hashlib.sha1(str(path).encode()).hexdigest() + '.wav')
    try:
        result = subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(path),'-vn','-c:a','pcm_f32le',str(dest)],
                                capture_output=True, text=True, timeout=300)
    except FileNotFoundError as exc:
        raise RuntimeError('FFmpeg required for MP3 stems') from exc
    if result.returncode or not dest.exists():
        raise RuntimeError(f'MP3 decoding failed for {path.name}: {result.stderr[-250:]}')
    return dest


def _stereo(data: np.ndarray, gain_db: float, pan: float) -> np.ndarray:
    if data.shape[1] not in (1, 2):
        raise ValueError('Only mono or stereo stems are supported')
    gain = 10 ** (gain_db / 20)
    if data.shape[1] == 1:
        # Mono center at equal-power pan; one sample channel routed to two outputs.
        angle = (pan + 1) * math.pi / 4
        return np.column_stack((data[:, 0] * math.cos(angle), data[:, 0] * math.sin(angle))) * gain
    # Preserve original stereo when pan=0, avoiding unwanted -3dB level change.
    return data * np.array([min(1., 1.-pan), min(1., 1.+pan)], dtype=np.float64) * gain


def _eq_stem(path: Path, output: Path, host: Path, plugin: Path, category: str) -> dict:
    from .host import run_host
    from .proq4 import build_changes
    suggestions = [{'center_hz': hz, 'recommended_gain_db': db} for hz, db in PRESETS[category]]
    inspected = run_host(host, 'inspect', plugin=plugin)
    changes = build_changes(inspected, suggestions, min_db=.3, max_bands=4)
    if changes:
        payload = run_host(host, 'render', plugin=plugin, input_file=path, output_file=output,
                           parameter_changes=changes, state_out=output.with_suffix('.state'), timeout=600)
        if not output.is_file() or output.stat().st_size < 44:
            raise RuntimeError(f'Host returned success but created no WAV: {path.name}')
        return {'render':payload, 'parameters':changes}
    return {'parameters':[], 'render':None}


def render_mix(folder: Path, config: dict, output: Path, *, host: Path | None = None,
               plugin: Path | None = None, ceiling_dbfs: float = -3.0, block: int = 32768, prepared: dict | None = None) -> dict:
    """Render a preview stereo mix, peak safety via uniform gain (not a limiter)."""
    if not -12 <= ceiling_dbfs <= -0.1:
        raise ValueError('ceiling_dbfs must be between -12 and -0.1')
    tracks = parse_tracks(config, folder)
    if output.resolve() in {t.path for t in tracks}:
        raise ValueError('Output cannot overwrite a stem')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aml-mix-') as temp:
        td = Path(temp)
        prepared_prints = prepared or {}
        prepared_tracks = []
        processed = []
        for i, t in enumerate(tracks):
            audio = decode_audio(t.path, td)
            # Prefer an explicitly selected, prepared wet print; never silently apply stale audio.
            wet = prepared_prints.get(str(i)) if config['tracks'][i].get('eq',False) else None
            if wet:
                candidate = Path(wet).resolve()
                if not candidate.is_file(): raise ValueError(f'Prepared FX missing: {candidate}')
                original_info = (sf.info(str(audio)).samplerate, sf.info(str(audio)).frames)
                wet_info = (sf.info(str(candidate)).samplerate, sf.info(str(candidate)).frames)
                if original_info != wet_info:
                    raise ValueError(f'FX audio alignment differs for {t.path.name}')
                audio = candidate
            elif t.eq and config['tracks'][i].get('fx_chain'):
                raise ValueError(f'No prepared FX print for {t.path.name}; prepare the chain before export')
            elif t.eq and not t.mute:
                if host is None or plugin is None:
                    raise ValueError('EQ enabled but no --host and --plugin supplied')
                converted = td / f'eq-{i}.wav'
                info = _eq_stem(audio, converted, host, plugin, classify_stem(t.path))
                processed.append({'file': str(t.path), 'eq': info})
                audio = converted
            prepared_tracks.append((t, audio))
        meta=[]
        for t, audio in prepared_tracks:
            with sf.SoundFile(str(audio)) as f:
                if f.channels not in (1,2):
                    raise ValueError(f'{t.path.name}: expected mono or stereo; got {f.channels}')
                meta.append((f.samplerate, len(f), f.channels))
        rates = {m[0] for m in meta}
        if len(rates) != 1:
            raise ValueError('Stems have different sample rates. Align/resample in Cubase first.')
        rate = meta[0][0]
        lengths = [m[1] for m in meta]
        if max(lengths) - min(lengths) > int(rate * .05):
            raise ValueError('Stems differ in duration by >50ms. Align stems in Cubase first.')
        frames = max(lengths)
        float_mix = td / 'sum-float.wav'
        peak = 0.
        handles = [sf.SoundFile(str(p)) for _,p in prepared_tracks]
        try:
            with sf.SoundFile(str(float_mix), mode='w', samplerate=rate, channels=2, subtype='FLOAT') as w:
                for pos in range(0, frames, block):
                    count = min(block, frames-pos)
                    summed = np.zeros((count,2), dtype=np.float64)
                    for (track,_), f in zip(prepared_tracks,handles):
                        if track.mute: continue
                        arr = f.read(count, dtype='float64', always_2d=True)
                        if len(arr) < count:
                            arr = np.pad(arr, ((0,count-len(arr)),(0,0)))
                        if not np.isfinite(arr).all():
                            raise ValueError('Nonfinite stem audio values')
                        summed += _stereo(arr,track.gain_db,track.pan)
                    peak = max(peak, float(np.max(np.abs(summed))))
                    w.write(summed.astype(np.float32))
        finally:
            for f in handles: f.close()
        ceiling = 10 ** (ceiling_dbfs/20)
        scale = min(1.0, ceiling / peak) if peak else 1.0
        # Staging destination atomically. This preview uses 24-bit PCM; protect against hard clipping.
        staging = output.with_name(output.stem + '.partial.wav')
        try:
            with sf.SoundFile(str(float_mix)) as r, sf.SoundFile(str(staging), 'w', samplerate=rate, channels=2, subtype='PCM_24') as w:
                while True:
                    part = r.read(block,dtype='float64',always_2d=True)
                    if not len(part): break
                    w.write((part * scale).astype(np.float32))
            staging.replace(output)
        finally:
            staging.unlink(missing_ok=True)
    report = {'status':'ok','output':str(output.resolve()),'sample_rate':rate,'duration_seconds':frames/rate,
              'tracks':[{'file':str(t.path), 'gain_db':t.gain_db,'pan':t.pan,'mute':t.mute,'eq':t.eq} for t in tracks],
              'pre_safety_peak_dbfs':20*math.log10(max(peak,1e-12)),
              'global_safety_gain_db':20*math.log10(max(scale,1e-12)),
              'ceiling_dbfs':ceiling_dbfs,'eq_processing':processed,
              'warnings':['Preview mix only: no true-peak limiting, latency alignment, sends, sidechains or AI repair.',
                          'Stem timing and phase must be checked against the original mix before mastering.']}
    report_path = output.with_suffix('.mix.json')
    report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    return report
