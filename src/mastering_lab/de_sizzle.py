"""Local broadband treble analysis and time-limited peaking EQ for stems."""
from pathlib import Path
import tempfile

import numpy as np
import soundfile as sf
from scipy.signal import freqz, lfilter

CENTER_HZ = 7500
MAX_PASSAGES = 12


def scan_sizzle(path, *, cancelled=lambda: False):
    """Flag sustained, noise-like bright passages after their initial attack."""
    size = 2048
    markers = []
    run = 0
    dry_energy = wet_energy = 0.0
    with sf.SoundFile(path) as audio:
        rate = audio.samplerate
        if rate < 32000:
            return []
        hz = np.fft.rfftfreq(size, 1 / rate)
        high = (hz >= 5000) & (hz <= 11500)
        presence = (hz >= 1000) & (hz < 5000)
        window = np.hanning(size)[:, None]
        b, a = _coefficients(rate)
        _, response = freqz(b, a, worN=2 * np.pi * hz / rate)
        response_power = abs(response[:, None]) ** 2
        for frame, block in enumerate(audio.blocks(blocksize=size, dtype='float32', always_2d=True)):
            if cancelled():
                return []
            if len(block) != size:
                break
            power = abs(np.fft.rfft(block * window, axis=0)) ** 2
            treble = power[high]
            mean = treble.mean(axis=0)
            flatness = np.exp(np.log(treble + 1e-12).mean(axis=0)) / (mean + 1e-12)
            loud = treble.sum(axis=0) >= 0.55 * power[presence].sum(axis=0)
            flagged = np.any(loud & (flatness > 0.24) & (mean > 0.04))
            if flagged:
                # Skip the first frame (attack) in both correction and matching.
                if run:
                    dry_energy += float(power.sum())
                    wet_energy += float((power * response_power).sum())
                run += 1
            elif run:
                _append(markers, frame, run, size / rate, dry_energy, wet_energy)
                run = 0
                dry_energy = wet_energy = 0.0
        if run:
            _append(markers, audio.frames // size, run, size / rate, dry_energy, wet_energy)
    return sorted(sorted(markers, key=lambda m: m['end'] - m['start'], reverse=True)[:MAX_PASSAGES],
                  key=lambda m: m['start'])


def _append(markers, end, run, step, dry, wet):
    if run * step >= 0.21:
        markers.append({'start': (end - run + 1) * step, 'end': end * step,
                        'hz': CENTER_HZ, 'kind': 'sizzle',
                        'match_db': float(np.clip(10 * np.log10(dry / max(wet, 1e-12)), 0, 1))})


def _coefficients(rate):
    gain = 10 ** (-3 / 40)
    w = 2 * np.pi * CENTER_HZ / rate
    alpha = np.sin(w) / (2 * 0.85)
    cosine = -2 * np.cos(w)
    return ([1 + alpha * gain, cosine, 1 - alpha * gain],
            [1 + alpha / gain, cosine, 1 - alpha / gain])


def render_passages(source, output, markers, *, stop=None):
    """Match the native 7.5 kHz, Q 0.85, -3 dB peak and 20 ms edge ramps."""
    from .auto_master import MasteringCancelled

    with sf.SoundFile(source) as reader:
        rate = reader.samplerate
        if rate < 32000:
            raise ValueError('De-Sizzle requires at least 32 kHz.')
        ranges = sorted((round(float(m['start']) * rate), round(float(m['end']) * rate))
                        for m in markers)
        if (not 1 <= len(ranges) <= MAX_PASSAGES
                or any(not 0 <= start < end <= reader.frames for start, end in ranges)):
            raise ValueError('Invalid De-Sizzle passages.')
        b, denominator = _coefficients(rate)
        state = np.zeros((2, reader.channels))
        pos = 0
        with sf.SoundFile(output, 'w', rate, reader.channels, format='WAV', subtype='FLOAT') as writer:
            for block in reader.blocks(blocksize=32768, dtype='float32', always_2d=True):
                if stop is not None and stop.is_set():
                    raise MasteringCancelled('De-Sizzle annulé.')
                filtered, state = lfilter(b, denominator, block, axis=0, zi=state)
                frames = pos + np.arange(len(block))
                mix = np.zeros(len(block))
                for start, end in ranges:
                    ramp = np.clip(np.minimum(frames - start, end - frames) / (0.02 * rate), 0, 1)
                    np.maximum(mix, ramp, out=mix)
                writer.write(block + (filtered - block) * mix[:, None])
                pos += len(block)


def prepare_de_sizzle(config, selections, prepared, directory, *, stop=None):
    """Replace prepared mixer inputs with aligned derivatives where approved."""
    directory = Path(directory)
    tracks = {track['file'] for track in config['tracks']}
    if set(selections) - tracks:
        raise ValueError('Un stem De-Sizzle approuvé a été déplacé ou supprimé.')
    for index, track in enumerate(config['tracks']):
        source = track['file']
        markers = selections.get(source)
        if not markers:
            continue
        key = str(index)
        output = directory / f'de-sizzle-{index}.wav'
        with tempfile.TemporaryDirectory(dir=directory) as tmp:
            partial = Path(tmp) / 'processed.wav'
            render_passages(prepared.get(key, source), partial, markers, stop=stop)
            partial.replace(output)
        prepared[key] = str(output)
