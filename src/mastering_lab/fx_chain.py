"""Non-destructive, per-stem offline VST3 chain preparation using existing JUCE host.

This is *not* real-time plugin hosting: each active effect is a separate host invocation.
Only preset/default plugin state can be applied; arbitrary VST control is not promised.
"""
from __future__ import annotations
import hashlib
import json
import math
import shutil
import tempfile
from pathlib import Path

import soundfile as sf

SUPPORTED_ROLES = ('corrective_eq', 'compression', 'resonance', 'reverb', 'color')


def validate_chain(chain: list[dict]) -> list[dict]:
    if not isinstance(chain, list) or len(chain) > 12:
        raise ValueError('FX chain must contain at most 12 effects')
    clean = []
    for step in chain:
        if not isinstance(step, dict):
            raise ValueError('Each FX step must be an object')
        role = str(step.get('role', ''))
        if role not in SUPPORTED_ROLES:
            raise ValueError(f'Unsupported stem FX role: {role}')
        plugin = Path(str(step.get('plugin', '')))
        if plugin.suffix.lower() != '.vst3' or not plugin.is_file() and not plugin.is_dir():
            raise ValueError(f'Plugin is missing or not a VST3: {plugin}')
        state_text = str(step.get('state_file', '')).strip()
        state = Path(state_text).resolve() if state_text else None
        if state is not None and not state.is_file():
            raise ValueError(f'Missing saved plugin state: {state}')
        clean.append({'role': role, 'plugin': str(plugin.resolve()),
                      'enabled': bool(step.get('enabled', True)),
                      'state_file': str(state) if state else ''})
    return clean


def _format_info(path: Path) -> tuple[int, int, int]:
    with sf.SoundFile(str(path)) as audio:
        if audio.channels not in (1, 2):
            raise ValueError(f'{path.name}: only mono/stereo supported')
        return audio.samplerate, len(audio), audio.channels


# A few dynamics plugins declare a small nonzero tail, which the JUCE host
# appends AFTER latency compensation. Preserve the original timeline by
# dropping only this *reported* short tail, never by resampling or shifting.
MAX_SHORT_TAIL_SAMPLES = 256
SHORT_TAIL_ROLES = frozenset({'compression', 'corrective_eq', 'resonance', 'color'})

def _normalize_short_tail(rendered_path: Path, expected: tuple[int, int, int],
                          reported: dict, role: str) -> int:
    sample_rate, expected_frames, channels = expected
    actual_rate, actual_frames, actual_channels = _format_info(rendered_path)
    if (actual_rate, actual_channels) != (sample_rate, channels):
        raise ValueError(f'FX changed sample rate or channel count: '
                         f'{(actual_rate, actual_channels)} vs {(sample_rate, channels)}')
    latency = int(reported.get('latency_samples', 0) or 0)
    tail = int(reported.get('tail_samples', 0) or 0)
    if latency < 0 or tail < 0:
        raise ValueError('Invalid VST latency or tail report')
    difference = actual_frames - expected_frames
    if difference == 0:
        if tail:
            raise ValueError('VST reports a tail but output length is unchanged; cannot verify timing')
        return 0
    if (difference < 0 or difference != tail or role not in SHORT_TAIL_ROLES
            or tail > MAX_SHORT_TAIL_SAMPLES):
        raise ValueError('FX output length mismatch: '
                         f'{actual_frames} vs {expected_frames} frames; '
                         f'reported tail={tail}, latency={latency}, role={role}. '
                         'Refusing to alter audio alignment.')
    trimmed = rendered_path.with_name(rendered_path.stem + '-trimmed.wav')
    try:
        with sf.SoundFile(str(rendered_path), 'r') as src:
            with sf.SoundFile(str(trimmed), mode='w', samplerate=sample_rate,
                              channels=channels, format='WAV', subtype=src.subtype) as dst:
                remaining = expected_frames
                while remaining:
                    chunk = src.read(min(65536, remaining), dtype='float64', always_2d=True)
                    if len(chunk) == 0:
                        raise ValueError('Unexpected EOF during short-tail removal')
                    dst.write(chunk)
                    remaining -= len(chunk)
        trimmed.replace(rendered_path)
    finally:
        trimmed.unlink(missing_ok=True)
    return difference


def prepare_chain(source: Path, chain: list[dict], out: Path, host: Path) -> dict:
    """Render effect stages sequentially. Fail safely if latency/length mismatches are found.

    Never overwrites an input. A single output commit happens after all stages succeed.
    """
    from .host import run_host
    source, out, host = Path(source).resolve(), Path(out).resolve(), Path(host).resolve()
    if not source.is_file() or source.suffix.lower() != '.wav':
        raise ValueError('FX preparation currently requires an existing WAV source')
    if source == out:
        raise ValueError('FX output cannot overwrite its source')
    if not host.is_file():
        raise ValueError(f'JUCE mastering-host not found: {host}')
    steps = validate_chain(chain)
    stages = [s for s in steps if s['enabled']]
    if not stages:
        raise ValueError('No enabled FX in this chain')
    expected = _format_info(source)
    if expected[2] != 2:
        raise ValueError('JUCE host currently supports stereo WAV; convert mono stem to stereo before FX preparation')
    # The JUCE host trims each plugin's reported latency from the rendered WAV.
    # Tail handling still requires a separate effects-bus workflow, so reject tails.
    out.parent.mkdir(parents=True, exist_ok=True)
    details = []
    with tempfile.TemporaryDirectory(prefix='aml-fx-chain-') as directory:
        td = Path(directory)
        current = source
        for i, stage in enumerate(stages):
            p = Path(stage['plugin'])
            inspected = run_host(host, 'inspect', plugin=p)
            render_to = td / f'stage-{i:02d}.wav'
            args = {'plugin': p, 'input_file': current, 'output_file': render_to, 'timeout': 600}
            if stage['state_file']:
                args['state_in'] = Path(stage['state_file'])
            rendered = run_host(host, 'render', **args)
            if not render_to.exists() or render_to.stat().st_size < 44:
                raise RuntimeError(f'{p.stem} did not produce a valid WAV')
            trimmed_tail = _normalize_short_tail(render_to, expected, rendered, stage['role'])
            reported_latency = int(rendered.get('latency_samples', 0) or 0)
            details.append({'role': stage['role'], 'plugin': stage['plugin'], 'state_file': stage['state_file'],
                            'latency_compensated_samples': reported_latency,
                            'trimmed_declared_tail_samples': trimmed_tail})
            current = render_to
        staged = out.with_name(out.name + '.tmp')
        try:
            shutil.copyfile(current, staged)
            staged.replace(out)
        finally:
            staged.unlink(missing_ok=True)
    return {'status': 'ok', 'source': str(source), 'output': str(out), 'stages': details,
            'note': 'Offline FX print, not live VST processing or a distribution-ready master'}


def chain_fingerprint(source: Path, chain: list[dict]) -> str:
    """Detect source, chain and plugin-state changes for cache identity."""
    s = Path(source)
    def info(p):
        p = Path(p)
        st = p.stat()
        return [str(p.resolve()), st.st_size, st.st_mtime_ns]
    stages = validate_chain(chain)
    blob = {'source': info(s), 'stages': [dict(step, plugin_meta=info(step['plugin']),
             state_meta=info(step['state_file']) if step['state_file'] else None) for step in stages]}
    return hashlib.sha256(json.dumps(blob, sort_keys=True).encode()).hexdigest()[:20]
