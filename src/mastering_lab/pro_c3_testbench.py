"""Isolated Pro-C 3 synthetic-audio bench. Never runs on user songs.

This is a diagnostic, NOT authorization for automatic compression. All audio
is generated internally and saved to a separately versioned diagnostics folder.
"""
from __future__ import annotations
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

RATE = 48000
SEGMENT_SECONDS = 1.0
PILOT_START = int(0.08 * RATE)
PILOT_LENGTH = int(0.06 * RATE)
PILOT_SEARCH = 512  # samples, intentionally bounded (< 11 ms at 48 kHz)
GAIN_CHANGE = (19, 0.0)  # Pro-C 3 Auto Gain OFF; verify plugin text before trusting metrics


def build_probe(path):
    """4-second alternating low/high amplitude sine, stereo; no external input."""
    t = np.arange(RATE * 4, dtype=np.float64) / RATE
    amp = np.where((t >= 1.0) & (t < 2.0) | (t >= 3.0), 0.50, 0.04)
    mono = (amp * np.sin(2.0 * math.pi * 440.0 * t)).astype('float32')
    # Low-level, deterministic, nonperiodic pilot in the quiet first segment.
    # Without it, 440 Hz phase matching has ambiguous lags at each cycle.
    rng = np.random.default_rng(4217)
    pilot = rng.choice([-1., 1.], size=PILOT_LENGTH).astype('float32') * 0.017
    # Soft taper to avoid clicks, no effect on stable RMS windows (0.2-0.8 s).
    fade = min(128, PILOT_LENGTH // 4)
    pilot[:fade] *= np.linspace(0, 1, fade, dtype='float32')
    pilot[-fade:] *= np.linspace(1, 0, fade, dtype='float32')
    mono[PILOT_START:PILOT_START+PILOT_LENGTH] = pilot
    stereo = np.repeat(mono[:, None], 2, axis=1)
    sf.write(str(path), stereo, RATE, subtype='PCM_24')


def _segment_rms(x, start, end, rate):
    # Avoid transitions and ramp-up; average a 0.6s stable window.
    lo, hi = int((start + 0.20) * rate), int((end - 0.20) * rate)
    y = x[lo:hi]
    return float(np.sqrt(np.mean(np.square(y.astype(np.float64)))))


def _db(x):
    return 20.0 * math.log10(max(x, 1e-12))


def inspect_render_shape(before, after, declared_tail=0):
    """Check actual WAV metadata; allow only a bounded *trailing* host tail.

    A declared tail is not evidence that the render actually contains a tail.
    Never repair a short file, changed channels or changed sample rate.
    """
    src, dst = sf.info(str(before)), sf.info(str(after))
    expected = {'frames': RATE * 4, 'channels': 2, 'sample_rate': RATE}
    observed = {'frames': int(dst.frames), 'channels': int(dst.channels),
                'sample_rate': int(dst.samplerate)}
    shapes = {'expected': expected, 'observed': observed,
              'source': {'frames': int(src.frames), 'channels': int(src.channels),
                         'sample_rate': int(src.samplerate)},
              'frame_delta': int(dst.frames - expected['frames']),
              'declared_tail_samples': int(declared_tail)}
    if (src.frames != expected['frames'] or src.channels != 2 or src.samplerate != RATE):
        raise ValueError(f'Signal synthétique source invalide : {shapes}')
    if dst.channels != 2 or dst.samplerate != RATE:
        raise ValueError(f'Rendu Pro-C 3 : canaux ou fréquence inattendus : {shapes}')
    delta = shapes['frame_delta']
    if delta < 0:
        raise ValueError(f'Rendu Pro-C 3 : durée tronquée : {shapes}')
    # Only trailing additions that match the host-declared tail are permitted.
    # Never infer alignment from equal duration or a tail report.
    if delta and (declared_tail <= 0 or delta != declared_tail):
        raise ValueError(f'Rendu Pro-C 3 : longueur non expliquée : {shapes}')
    shapes['trailing_tail_for_measurement'] = delta
    return shapes


def measure_pilot_alignment(before, after, *, max_lag=PILOT_SEARCH):
    """Diagnostic only: locate a unique broadband pilot within ±max_lag frames.

    Returns confidence/lag, never asserts exact full-song compensation or enables
    production compression. A failed correlation is inconclusive rather than a
    reason to cut, pad or time-shift user audio.
    """
    source, rate1 = sf.read(str(before), dtype='float32', always_2d=True)
    output, rate2 = sf.read(str(after), dtype='float32', always_2d=True)
    if rate1 != RATE or rate2 != RATE or source.shape[1] != 2 or output.shape[1] != 2:
        raise ValueError('Pilot : format audio incompatible.')
    reference = source[PILOT_START:PILOT_START + PILOT_LENGTH].mean(axis=1).astype('float64')
    reference -= reference.mean()
    ref_norm = float(np.linalg.norm(reference))
    if ref_norm <= 1e-8:
        raise ValueError('Pilot : signal de référence manquant.')
    best = (-1., None, None)
    # Offset relative to pilot location in original. Negative offset is allowed.
    for lag in range(-max_lag, max_lag + 1):
        start = PILOT_START + lag
        if start < 0 or start + PILOT_LENGTH > len(output):
            continue
        segment = output[start:start + PILOT_LENGTH].mean(axis=1).astype('float64')
        segment -= segment.mean()
        energy = float(np.linalg.norm(segment))
        if energy <= 1e-10:
            continue
        correlation = float(np.dot(reference, segment) / (ref_norm * energy))
        if correlation > best[0]:
            best = (correlation, lag, energy)
    correlation, lag, _ = best
    if lag is None:
        return {'status': 'inconclusive', 'reason': 'Aucune fenêtre de test disponible.',
                'max_lag_frames': max_lag}
    confident = correlation >= .85
    return {'status': 'measured' if confident else 'inconclusive',
            'pilot_lag_frames': int(lag) if confident else None,
            'pilot_lag_ms': round(float(lag) * 1000 / RATE, 4) if confident else None,
            'correlation': round(correlation, 5),
            'max_lag_frames': max_lag,
            'note': ('Décalage estimé sur pilot synthétique seulement; '
                     'ne valide ni compensation de latence générale ni mapping Pro-C 3.')}


def measure_response(before, after, *, declared_tail=0, shape_info=None):
    shapes = shape_info or inspect_render_shape(before, after, declared_tail)
    a, ra = sf.read(str(before), dtype='float32', always_2d=True)
    b, rb = sf.read(str(after), dtype='float32', always_2d=True)
    # A matching *trailing* tail is excluded from RMS windows, never treated
    # as a validated time alignment. Keep the full original output on disk.
    b = b[:RATE * 4]
    if ra != RATE or rb != RATE or a.shape != b.shape or a.shape != (RATE * 4, 2):
        raise ValueError(f'Rendu Pro-C 3 : dimensions après lecture inattendues : {shapes}')
    if not np.all(np.isfinite(b)):
        raise ValueError('Rendu Pro-C 3 : échantillons non finis.')
    before_segments = [_segment_rms(a, i, i + 1, RATE) for i in range(4)]
    after_segments = [_segment_rms(b, i, i + 1, RATE) for i in range(4)]
    before_db = [_db(v) for v in before_segments]
    after_db = [_db(v) for v in after_segments]
    high_attenuation_db = (before_db[1] - after_db[1] + before_db[3] - after_db[3]) / 2
    low_attenuation_db = (before_db[0] - after_db[0] + before_db[2] - after_db[2]) / 2
    peak = float(np.max(np.abs(b)))
    return {
        'before_rms_dbfs': before_db,
        'after_rms_dbfs': after_db,
        'high_level_attenuation_db': round(high_attenuation_db, 3),
        'low_level_attenuation_db': round(low_attenuation_db, 3),
        'processed_sample_peak_dbfs': round(_db(peak), 3),
        'nonzero_output': bool(np.any(b != 0)),
        'compression_observed': bool(high_attenuation_db > 2.0 and high_attenuation_db > low_attenuation_db + 1.0 and peak < 1.0),
    }


def _verified_plugin(info):
    if 'pro-c 3' not in str(info.get('name', '')).lower():
        raise ValueError('Le host n’a pas confirmé FabFilter Pro-C 3.')
    params = info.get('parameters', [])
    if not isinstance(params, list):
        raise ValueError('Inspection Pro-C 3 invalide.')
    expected = {1:'Threshold', 4:'Ratio', 7:'Attack', 8:'Release', 19:'Auto Gain'}
    for idx, name in expected.items():
        if idx >= len(params) or params[idx].get('index') != idx or params[idx].get('name') != name or not params[idx].get('automatable'):
            raise ValueError(f'Pro-C 3 : mapping non confirmé pour {name} (index {idx}).')


def bench_and_save(root, *, host=None, plugin=None, runner=None):
    """Run only on generated source. No song path is accepted by this API."""
    root = Path(root).resolve()
    host = Path(host or root / 'native/build/mastering-host_artefacts/Release/mastering-host.exe').resolve()
    plugin = Path(plugin or 'C:/Program Files/Common Files/VST3/FabFilter/FabFilter Pro-C 3.vst3').resolve()
    if not host.is_file() or not plugin.exists() or plugin.suffix.lower() != '.vst3':
        raise FileNotFoundError('mastering-host.exe ou Pro-C 3.vst3 introuvable.')
    if runner is None:
        from .host import run_host
        runner = run_host
    info = runner(host, 'inspect', plugin=plugin, timeout=90)
    _verified_plugin(info)
    base = root / 'settings' / 'pro_c3_testbench'
    base.mkdir(parents=True, exist_ok=True)
    # Unique run directory, never overwrite a past run.
    from uuid import uuid4
    folder = base / (datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    folder.mkdir(exist_ok=False)
    before = folder / 'synthetic-before.wav'
    after = folder / 'synthetic-after-pro-c3.wav'
    report_path = folder / 'report.json'
    report = {'schema_version': 1, 'kind': 'pro_c3_synthetic_test', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'plugin': str(plugin), 'host': str(host), 'auto_gain_requested': 'Off',
              'ready_to_render': False, 'automatic_compression_enabled': False,
              'status': 'not_validated'}
    try:
        build_probe(before)
        result = runner(host, 'render', plugin=plugin, input_file=before, output_file=after,
                        parameter_changes=[GAIN_CHANGE], timeout=180)
        changes = {v.get('index'):v for v in result.get('parameter_changes', [])}
        text = str(changes.get(19, {}).get('text', '')).strip().lower()
        if text != 'off':
            raise ValueError(f'Pro-C 3 Auto Gain non confirmé OFF : {text!r}')
        # JUCE tail_samples describes the plugin's declared release/tail. It does
        # NOT by itself show that the rendered file contains extra audio or that
        # its first sample is offset. Treat it as an alignment caveat, not failure.
        declared_tail = int(result.get('tail_samples', 0) or 0)
        if declared_tail < 0:
            raise ValueError('Queue audio invalide signalée par JUCE.')
        report['declared_tail_samples'] = declared_tail
        report['temporal_alignment'] = ('not_verified_tail_reported' if declared_tail
                                        else 'not_verified_no_declared_tail')
        if not after.is_file():
            raise ValueError('Aucun fichier de sortie JUCE généré.')
        report['wav_shape'] = inspect_render_shape(before, after, declared_tail)
        report['measurements'] = measure_response(before, after, declared_tail=declared_tail, shape_info=report['wav_shape'])
        report['auto_gain_confirmed'] = True
        report['pilot_alignment'] = measure_pilot_alignment(before, after)
        report['status'] = ('observed' if report['measurements']['compression_observed'] and declared_tail == 0
                            else 'needs_review')
        if declared_tail:
            frames_extra = report['wav_shape']['trailing_tail_for_measurement']
            report['warning'] = ('Pro-C 3 déclare une queue de ' + str(declared_tail)
                                 + ' échantillons; le WAV contient ' + str(frames_extra)
                                 + ' frame(s) supplémentaires. La queue éventuelle a été exclue '
                                 'des mesures, mais l’alignement exact reste à vérifier.')
        report['note'] = ('Mesures sur signal synthétique seulement; le mapping des paramètres n’est pas encore '
                          'suffisamment validé pour autoriser la compression automatique de chansons.')
    except Exception as exc:
        if after.is_file():
            try:
                report['wav_shape'] = {
                    'expected': {'frames': RATE * 4, 'channels': 2, 'sample_rate': RATE},
                    'observed': {'frames': int(sf.info(str(after)).frames),
                                 'channels': int(sf.info(str(after)).channels),
                                 'sample_rate': int(sf.info(str(after)).samplerate)},
                }
            except Exception as metadata_exc:
                report['wav_metadata_error'] = str(metadata_exc)
        report['status'] = 'failed'
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        temp = report_path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(report_path)
    report['report_path'] = str(report_path)
    report['before_path'] = str(before)
    report['after_path'] = str(after)
    return report


def summarize(report):
    m = report.get('measurements', {})
    lines = ['Pro-C 3 — Compression Test Bench', 'Signal : WAV stéréo synthétique 440 Hz, niveaux alternés',
             f"Statut : {report.get('status', 'inconnu')}",
             'Compression automatique : TOUJOURS VERROUILLÉE']
    if m:
        lines += [f"Atténuation passages forts : {m['high_level_attenuation_db']:+.2f} dB",
                  f"Atténuation passages faibles : {m['low_level_attenuation_db']:+.2f} dB",
                  f"Crête échantillon : {m['processed_sample_peak_dbfs']:+.2f} dBFS",
                  f"Compression observée : {'oui' if m['compression_observed'] else 'non — à examiner'}"]
    if 'declared_tail_samples' in report:
        lines.append(f"Queue déclarée par Pro-C 3 : {report['declared_tail_samples']} échantillons (information JUCE)")
    align = report.get('pilot_alignment')
    if align:
        if align['status'] == 'measured':
            lines.append(f"Décalage du signal pilote : {align['pilot_lag_frames']:+d} frame(s) "
                         f"({align['pilot_lag_ms']:+.3f} ms), corrélation {align['correlation']:.3f}")
        else:
            lines.append(f"Alignement du signal pilote : non concluant "
                         f"(corrélation {align.get('correlation', 0):.3f})")
    if report.get('warning'):
        lines.append('Attention : ' + report['warning'])
    if report.get('wav_shape'):
        shape = report['wav_shape']
        lines.append(f"WAV attendu : {shape.get('expected')}")
        lines.append(f"WAV rendu : {shape.get('observed')}")
        if 'trailing_tail_for_measurement' in shape:
            lines.append(f"Frames de queue exclus des mesures : {shape['trailing_tail_for_measurement']}")
    if report.get('error'):
        lines.append('Erreur : ' + report['error'])
    lines.append('Alignement temporel exact NON validé ; compression automatique verrouillée.')
    lines.append('Ce test ne valide PAS à lui seul le mapping physique des paramètres ni le mastering musical.')
    return '\n'.join(lines)
