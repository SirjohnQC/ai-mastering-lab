"""First Auto Master stage: two-pass EBU R128 FFmpeg + independently checked WAV.

This is a technical loudness/true-peak pass, NOT a substitute for tonal mastering,
critical listening, or album consistency checks. Source files are never overwritten.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


class MasteringError(RuntimeError):
    pass


class MasteringCancelled(MasteringError):
    pass


def _json_report(output: str) -> dict:
    """FFmpeg prints loudnorm JSON to stderr among other diagnostics."""
    for matched in reversed(list(re.finditer(r'\{[^{}]*"input_i"[^{}]*\}', output, re.S))):
        try:
            value = json.loads(matched.group(0))
            if 'input_tp' in value and 'input_lra' in value:
                return value
        except (ValueError, TypeError):
            pass
    raise MasteringError('FFmpeg n’a pas retourné de mesures EBU R128 exploitables. ' + output[-1300:])


def _ffmpeg(args: list[str], *, stop=None, limit=3600) -> str:
    import time
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, errors='replace', encoding='utf-8')
    # communicate(timeout=...) prevents deadlock due to stderr pipe buffers.
    start = time.monotonic()
    while True:
        if stop is not None and stop.is_set():
            proc.kill()
            proc.communicate()
            raise MasteringCancelled('Auto Master annulé. Les fichiers originaux sont intacts.')
        try:
            _out, err = proc.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() - start > limit:
                proc.kill()
                proc.communicate()
                raise MasteringError('FFmpeg a dépassé le délai autorisé.')
    if proc.returncode:
        raise MasteringError('FFmpeg a échoué : ' + err[-1800:])
    return err


def _measure(ffmpeg: str, source: Path, *, stop=None) -> dict:
    report = _ffmpeg([ffmpeg, '-hide_banner', '-nostats', '-i', str(source),
        '-vn', '-af', 'loudnorm=I=-14:TP=-1:LRA=11:print_format=json',
        '-f', 'null', os.devnull], stop=stop)
    return _json_report(report)


def _probe_wav(path: Path) -> dict:
    import soundfile as sf
    with sf.SoundFile(str(path)) as f:
        return {'sample_rate': f.samplerate, 'channels': f.channels,
                'frames': f.frames, 'format': f.format, 'subtype': f.subtype,
                'duration_seconds': round(f.frames / f.samplerate, 3)}


def _sample_peak(path: Path) -> float:
    import numpy as np
    import soundfile as sf
    peak = 0.0
    with sf.SoundFile(str(path)) as f:
        while True:
            x = f.read(262144, dtype='float32', always_2d=True)
            if not len(x): break
            peak = max(peak, float(np.max(np.abs(x))))
    return 20 * math.log10(peak) if peak > 0 else float('-inf')


def master_song(source, output_dir, *, target_lufs=-14.0, target_tp=-1.0,
                stop=None, progress=None, ffmpeg_path=None) -> dict:
    """Master one stereo WAV with verified output. Returns JSON-compatible report."""
    source = Path(source).resolve()
    if not source.is_file():
        raise MasteringError(f'Fichier introuvable : {source}')
    if source.suffix.lower() != '.wav':
        raise MasteringError('Auto Master v1 exige un WAV stéréo; les autres formats viendront.')
    ffmpeg = ffmpeg_path or shutil.which('ffmpeg')
    if not ffmpeg:
        raise MasteringError('FFmpeg introuvable. Installe FFmpeg et redémarre AI Mastering Lab.')
    if not (-20 <= target_lufs <= -10 and -2.5 <= target_tp <= -0.5):
        raise MasteringError('Cibles LUFS/TP hors limites de sécurité.')
    meta = _probe_wav(source)
    if meta['channels'] != 2 or meta['frames'] == 0:
        raise MasteringError('Auto Master nécessite un WAV stéréo non vide.')
    dest = Path(output_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out = dest / f'{source.stem}-master-{stamp}.wav'
    tmp = dest / f'.{source.stem}-master-{stamp}.partial.wav'

    def notify(stage, percent):
        if progress: progress(stage, percent)

    try:
        notify('Mesure loudness du mix', 10)
        before = _measure(ffmpeg, source, stop=stop)
        needed = ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset')
        try:
            values = {k: float(before[k]) for k in needed}
        except (KeyError, TypeError, ValueError) as exc:
            raise MasteringError('Mesures FFmpeg incomplètes : '+str(exc)) from exc
        if not all(math.isfinite(v) for v in values.values()):
            raise MasteringError('Le WAV ne permet pas une mesure loudness fiable (silence ?).')
        notify('Auto Master : normalisation et contrôle des crêtes', 38)
        af = (f'loudnorm=I={target_lufs}:TP={target_tp}:LRA=11:'
              f'measured_I={values["input_i"]}:measured_TP={values["input_tp"]}:'
              f'measured_LRA={values["input_lra"]}:measured_thresh={values["input_thresh"]}:'
              f'offset={values["target_offset"]}:linear=true:print_format=json')
        render_report = _ffmpeg([ffmpeg, '-hide_banner', '-nostats', '-y', '-i', str(source),
            '-vn', '-af', af, '-ar', str(meta['sample_rate']), '-ac', '2',
            '-c:a', 'pcm_s24le', str(tmp)], stop=stop)
        rendered = _json_report(render_report)
        notify('Vérification indépendante du WAV final', 77)
        after = _measure(ffmpeg, tmp, stop=stop)
        output_meta = _probe_wav(tmp)
        if output_meta['sample_rate'] != meta['sample_rate'] or output_meta['channels'] != 2 or output_meta['subtype'] != 'PCM_24':
            raise MasteringError('Échec vérification : format du WAV exporté incorrect.')
        # FFmpeg loudnorm can introduce a slight leading/trailing delay.
        if abs(output_meta['duration_seconds'] - meta['duration_seconds']) > 0.1:
            raise MasteringError('Échec vérification : durée anormalement différente après mastering.')
        measured_lufs = float(after['input_i'])
        measured_tp = float(after['input_tp'])
        measured_peak = _sample_peak(tmp)
        issues = []
        if not math.isfinite(measured_lufs) or abs(measured_lufs - target_lufs) > 1.0:
            issues.append(f'LUFS hors tolérance : {measured_lufs:.2f} (cible {target_lufs:.1f})')
        if not math.isfinite(measured_tp) or measured_tp > target_tp + 0.2:
            issues.append(f'True peak trop élevé : {measured_tp:.2f} dBTP (cible {target_tp:.1f})')
        if measured_peak > 0.0:
            issues.append(f'Sample peak positif : {measured_peak:.2f} dBFS')
        if stop is not None and stop.is_set():
            raise MasteringCancelled('Auto Master annulé.')
        # Preserve diagnostic WAV on QC failure, but never label it as an approved master.
        if issues:
            rejected = dest / f'{source.stem}-QC-REVIEW-{stamp}.wav'
            tmp.replace(rejected)
            exported = rejected
        else:
            tmp.replace(out)
            exported = out
        result = {
            'status': 'qc_pass' if not issues else 'needs_review',
            'file': str(exported), 'source': str(source), 'input': meta,
            'output': _probe_wav(exported), 'input_lufs': float(before['input_i']),
            'input_true_peak_dbtp': float(before['input_tp']),
            'output_lufs': measured_lufs, 'output_true_peak_dbtp': measured_tp,
            'output_sample_peak_dbfs': measured_peak,
            'target_lufs': target_lufs, 'target_true_peak_dbtp': target_tp,
            'ffmpeg_normalization_mode': rendered.get('normalization_type', 'unknown'),
            'qc_issues': issues,
            'scope': ('Première passe technique : loudness / true peak / PCM24. '
                      'Écoute critique, traitement tonal artistique et cohérence album NON certifiés.'),
        }
        (exported.with_suffix('.qc.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        notify('Master terminé — rapport QC disponible', 100)
        return result
    except Exception:
        if tmp.exists():
            try: tmp.unlink()
            except OSError: pass
        raise
