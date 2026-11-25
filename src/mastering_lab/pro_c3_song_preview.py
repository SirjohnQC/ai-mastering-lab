"""Explicit, sandboxed real-mix Pro-C 3 preview. NEVER modifies a source or a master.

This experimental audition does not authorize Auto Produce, Hermes learning,
mastering or deployment of Pro-C 3 on songs without further validation.
"""
from __future__ import annotations
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

from .pro_c3_parameter_validation import prepare_scenario, validate_readback, SCENARIOS
from .pro_c3_testbench import _verified_plugin
from .pro_c3_loudness_match import build_playback_matching
from .adaptive_pro_c3 import prepare_adaptive
from .pro_c3_parameter_validation import prepare_discrete_scenario
from .smart_gentle import gentle_candidates, evaluate_gentle, choose_gentle

MIN_FRAMES, MAX_FRAMES, RATE = 48000 * 2, 48000 * 600, 48000


def verify_source(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != '.wav':
        raise ValueError('Sélectionne un fichier WAV non compressé.')
    info = sf.info(str(path))
    if info.channels != 2 or info.samplerate != RATE or not MIN_FRAMES <= info.frames <= MAX_FRAMES:
        raise ValueError('Pour ce premier essai : WAV stéréo 48 kHz de 2 secondes à 10 minutes seulement.')
    if info.format != 'WAV':
        raise ValueError('Le fichier doit être un véritable WAV.')
    return path, info


def verify_output(path, source_info, tail_samples):
    """Check identity and basic safety, NOT global temporal alignment."""
    if not isinstance(tail_samples, int) or not 0 <= tail_samples <= 48000:
        raise ValueError('Queue déclarée hors limites.')
    info = sf.info(str(path))
    delta = info.frames - source_info.frames
    if info.channels != 2 or info.samplerate != RATE or delta not in (0, tail_samples) or delta < 0:
        raise ValueError(f'Dimensions inattendues : {info.frames} frames / {info.channels} canaux / {info.samplerate} Hz, attendues {source_info.frames} (+{tail_samples} maximum).')
    # Streaming scan keeps memory bounded on lengthy mixes.
    peak = 0.0
    has_sound = False
    with sf.SoundFile(str(path)) as stream:
        remaining = int(source_info.frames)
        while remaining > 0:
            chunk = stream.read(min(remaining, 65536), dtype='float32', always_2d=True)
            if not len(chunk):
                raise ValueError('Rendu audio tronqué.')
            if not np.isfinite(chunk).all():
                raise ValueError('Rendu audio contient NaN ou infini.')
            peak = max(peak, float(np.max(np.abs(chunk))))
            has_sound |= bool(np.any(chunk != 0))
            remaining -= len(chunk)
    if not has_sound or peak >= 0.999:
        raise ValueError('Rendu silencieux ou écrêté : écoute refusée.')
    return {'frames': int(info.frames), 'channels': info.channels, 'sample_rate': info.samplerate,
            'extra_tail_frames': int(delta), 'sample_peak_dbfs': round(20 * math.log10(max(peak, 1e-12)), 2)}


def make_preview(root, source, *, host=None, plugin=None, runner=None, song_aware=False, smart_gentle=False):
    """Create immutable session with Original/Gentle/Firm audition copies.

    Caller must obtain explicit UI consent and invoke on a worker thread.
    Reports never mark mapping_verified or enable automatic song processing.
    """
    root = Path(root).resolve()
    source, info = verify_source(source)
    base = root / 'settings' / 'pro_c3_song_previews'
    # No implicit reuse of a master or production export location.
    if source.is_relative_to(base.resolve()) or source.is_relative_to((root / 'settings/pro_c3_parameter_validation').resolve()):
        raise ValueError('Choisis ton mix original, pas une sortie de test.')
    host = Path(host or root / 'native/build/mastering-host_artefacts/Release/mastering-host.exe').resolve()
    plugin = Path(plugin or 'C:/Program Files/Common Files/VST3/FabFilter/FabFilter Pro-C 3.vst3').resolve()
    if not host.is_file() or not plugin.exists() or plugin.suffix.lower() != '.vst3':
        raise FileNotFoundError('Host JUCE ou plugin FabFilter Pro-C 3 introuvable.')
    if runner is None:
        from .host import run_host
        runner = run_host
    grid = json.loads((root / 'settings/pro_c3_multipoint.json').read_text(encoding='utf-8'))
    inspection = runner(host, 'inspect', plugin=plugin, timeout=90)
    _verified_plugin(inspection)
    # Validate full calibration BEFORE copying or processing any user audio.
    if smart_gentle and not song_aware:
        raise ValueError('Smart Gentle requires validated song-aware calibration.')
    if song_aware:
        adaptive_plan, prepared = prepare_adaptive(grid, source)
    else:
        adaptive_plan = None
        prepared = {key: prepare_scenario(grid, key) for key in SCENARIOS}
    session = base / (datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    session.mkdir(parents=True, exist_ok=False)
    report_file = session / 'report.json'
    report = {'schema_version':1, 'kind':'pro_c3_manual_song_preview', 'created_utc':datetime.now(timezone.utc).isoformat(),
              'status':'failed', 'automatic_compression_enabled':False, 'ready_to_render':False,
              'mapping_verified':False, 'use_for_hermes':False,
              'song_aware_preview':bool(song_aware), 'smart_gentle_preview':bool(smart_gentle),
              'adaptive_plan':adaptive_plan, 'source_name':source.name,
              'source_path':str(source), 'source_frames':int(info.frames), 'sample_rate':RATE,
              'scenarios':{}, 'note':'Écoute expérimentale sur COPIES, approuvée manuellement. Aucune exportation de master.'}
    try:
        original = session / 'original.wav'
        shutil.copyfile(source, original)
        if original.stat().st_size != source.stat().st_size:
            raise ValueError('Copie du WAV source incomplète.')
        if smart_gentle:
            # Only two exact previously probed threshold points; never guess
            # arbitrary values between them or alter a user's original.
            trial_results = []
            for label, values in gentle_candidates(adaptive_plan['scenarios']['gentle']):
                expected, changes = prepare_discrete_scenario(grid, values)
                trial_output = session / (label + '.wav')
                rendered = runner(host, 'render', plugin=plugin,
                                  input_file=original, output_file=trial_output,
                                  parameter_changes=changes, timeout=900)
                checked = validate_readback(rendered, expected)
                tail = int(rendered.get('tail_samples', -1))
                shape = verify_output(trial_output, info, tail)
                metrics = evaluate_gentle(original, trial_output, frames=int(info.frames))
                trial_results.append({'name':label, 'threshold':values['threshold'],
                                      'path':str(trial_output), 'metrics':metrics,
                                      'parameters':checked, 'tail_samples':tail,
                                      'shape':shape, 'settings':values})
            decision = choose_gentle(trial_results)
            gentle_output = session / 'gentle.wav'
            if decision['status'] == 'selected':
                selected = next(item for item in trial_results
                                if item['name'] == decision['selected'])
                shutil.copyfile(selected['path'], gentle_output)
                report['scenarios']['gentle'] = {
                    'parameters':selected['parameters'],
                    'tail_samples':selected['tail_samples'],
                    'output_path':str(gentle_output),
                    'shape':verify_output(gentle_output, info, selected['tail_samples'])}
                adaptive_plan['scenarios']['gentle'] = selected['settings']
            else:
                # A valid third choice must remain auditable; the Gentle slot
                # is an explicit Original fallback, not fake compression.
                shutil.copyfile(original, gentle_output)
                report['scenarios']['gentle'] = {
                    'parameters':{},'tail_samples':0,
                    'output_path':str(gentle_output),
                    'shape':verify_output(gentle_output, info, 0),
                    'fallback_original':True}
            report['smart_gentle'] = {
                'status':decision['status'], 'selected':decision['selected'],
                'reason':decision['reason'],
                'candidates':[{
                    'name':x['name'], 'threshold_normalized':x['threshold'],
                    'metrics':x['metrics'], 'parameters':x['parameters']}
                    for x in trial_results],
                'note':'Measured WAV trial, not VST gain reduction. No mastering approval.'}
        for name in ('firm',) if smart_gentle else SCENARIOS:
            expected, changes = prepared[name]
            output = session / f'{name}.wav'
            result = runner(host, 'render', plugin=plugin, input_file=original, output_file=output,
                            parameter_changes=changes, timeout=900)
            checked = validate_readback(result, expected)
            tail = int(result.get('tail_samples', -1))
            shape = verify_output(output, info, tail)
            report['scenarios'][name] = {'parameters':checked, 'tail_samples':tail,
                                         'output_path':str(output), 'shape':shape}
        try:
            report['playback_matching'] = build_playback_matching(
                {'original': original, 'gentle': session / 'gentle.wav', 'firm': session / 'firm.wav'},
                source_frames=int(info.frames), sample_rate=RATE)
        except Exception as match_exc:
            report['playback_matching'] = {'status':'unavailable', 'error':str(match_exc)}
        report['status'] = 'needs_review'
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        temp = report_file.with_suffix('.json.tmp')
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(report_file)
    report['report_path'] = str(report_file)
    return report


def audition_files(root, report):
    """Only return files from a complete, self-contained generated session."""
    if report.get('kind') != 'pro_c3_manual_song_preview' or report.get('status') != 'needs_review':
        raise ValueError('Rapport incomplet : impossible de lancer l’écoute.')
    if report.get('automatic_compression_enabled') is not False or report.get('ready_to_render') is not False:
        raise ValueError('Rapport incompatible avec le mode laboratoire.')
    base = (Path(root).resolve() / 'settings/pro_c3_song_previews').resolve()
    session = Path(report['report_path']).resolve().parent
    if session.parent != base:
        raise ValueError('Le rapport pointe hors des sessions autorisées.')
    result = {'original':session / 'original.wav'}
    if set(report.get('scenarios', {})) != {'gentle', 'firm'}:
        raise ValueError('Rendus de compression incomplets.')
    for kind in ('gentle', 'firm'):
        recorded = Path(report['scenarios'][kind]['output_path']).resolve()
        expected = session / f'{kind}.wav'
        if recorded != expected.resolve():
            raise ValueError('Chemin de rendu non autorisé.')
        result[kind] = expected
    if not all(p.is_file() and p.resolve().parent == session for p in result.values()):
        raise FileNotFoundError('Copie audio de prévisualisation manquante.')
    return result


def save_choice(root, report, selected):
    """Store a MANUAL session choice; do not train Hermes on it."""
    if selected not in ('original','gentle','firm'):
        raise ValueError('Choix inconnu.')
    audition_files(root, report)
    path = (Path(root).resolve() / 'settings/pro_c3_song_preview_choices.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    item = {'kind':'manual_song_preview_choice','selected':selected,'created_utc':datetime.now(timezone.utc).isoformat(),
            'session':Path(report['report_path']).resolve().parent.name, 'use_for_hermes':False,
            'automatic_compression_enabled':False}
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(item, ensure_ascii=False) + '\n')
    return path
