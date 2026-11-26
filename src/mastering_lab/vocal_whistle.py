"""Find persistent narrow peaks in a vocal spectrogram for manual audition."""
from __future__ import annotations

import numpy as np
import soundfile as sf


def scan_vocal_whistles(path, *, cancelled=lambda: False):
    """Return up to twelve time-localized candidates, strongest first."""
    size = 8192
    hop = size // 2
    window = np.hanning(size)[:, None]
    markers = []
    current = None

    with sf.SoundFile(str(path)) as audio:
        rate = audio.samplerate
        step = rate / size
        min_frames = max(3, int(np.ceil(0.25 * rate / hop)))
        bins = np.arange(max(13, int(np.ceil(3500 / step))),
                         min(size // 2 - 12, int(min(12000, rate * 0.48) / step) + 1))
        if not bins.size:
            return []
        duration = audio.frames / rate

        for offset, block in enumerate(audio.blocks(
                blocksize=size, overlap=hop, dtype='float32', always_2d=True)):
            if cancelled():
                return []
            peak = None
            if len(block) == size:
                amplitude = np.abs(np.fft.rfft(block * window, axis=0))
                # Search channels independently so opposite-phase stereo tones survive.
                db = 20 * np.log10(np.maximum(amplitude * (2 / window.sum()), 1e-8))
                neighbors = np.stack([db[bins + delta] for delta in (-12, -8, -5, 5, 8, 12)])
                prominence = db[bins] - np.median(neighbors, axis=0)
                eligible = ((db[bins] >= -47) & (prominence >= 18)
                            & (db[bins] >= db[bins - 1]) & (db[bins] > db[bins + 1])
                            & (db[bins] - np.maximum(db[bins - 3], db[bins + 3]) >= 10))
                scores = np.where(eligible, db[bins] + 0.4 * prominence, -np.inf)
                row, channel = np.unravel_index(scores.argmax(), scores.shape)
                if eligible[row, channel]:
                    center = bins[row]
                    left, middle, right = db[center - 1:center + 2, channel]
                    correction = 0.5 * (left - right) / (left - 2 * middle + right)
                    hz = (center + correction) * step
                    if 3500 <= hz <= 12000 and hz < rate * 0.48:
                        peak = (hz, float(scores[row, channel]))

            start = offset * hop / rate
            if current is not None and (peak is None or abs(peak[0] - current['hz']) > 2 * step):
                if current['frames'] >= min_frames:
                    markers.append(current)
                current = None
            if peak is not None:
                if current is None:
                    current = {'start': start, 'hz': float(peak[0]), 'frames': 0, 'score': peak[1]}
                current['frames'] += 1
                current['end'] = min(duration, start + size / rate)
                if peak[1] > current['score']:
                    current['hz'], current['score'] = float(peak[0]), peak[1]

        if current is not None and current['frames'] >= min_frames:
            markers.append(current)

    strongest = sorted(markers, key=lambda item: item['score'], reverse=True)[:12]
    return [{key: marker[key] for key in ('start', 'end', 'hz')}
            for marker in sorted(strongest, key=lambda item: item['start'])]
