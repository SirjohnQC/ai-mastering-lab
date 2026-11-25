"""Local, sample-synchronous A/B monitoring. Does not modify mastering files.

Requires numpy, soundfile and sounddevice. Tracks are loaded into RAM once, so
profile switches don't reopen audio devices or seek separate media players.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import tempfile
import threading
import shutil

import numpy as np
import soundfile as sf


def _load(path: Path) -> tuple[np.ndarray, int]:
    """Load stereo PCM/FLAC (and MP3 when supported by libsndfile); FFmpeg fallback."""
    try:
        data, rate = sf.read(str(path), dtype='float32', always_2d=True)
    except (RuntimeError, sf.LibsndfileError):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            raise RuntimeError(f'Cannot decode {path.name}: FFmpeg is not on PATH')
        with tempfile.TemporaryDirectory(prefix='aml_ab_') as tmp:
            decoded = Path(tmp) / 'audio.wav'
            r = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(path),
                                '-c:a', 'pcm_f32le', str(decoded)], capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f'FFmpeg decode failed: {r.stderr[-500:]}')
            data, rate = sf.read(str(decoded), dtype='float32', always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    if data.shape[1] != 2:
        raise ValueError(f'{path.name}: expected mono/stereo, got {data.shape[1]} channels')
    return np.ascontiguousarray(data), int(rate)


def prepare_tracks(paths: dict[str, Path], gains: dict[str, float] | None = None) -> tuple[dict[str, np.ndarray], int]:
    """Decode tracks and apply comparison-only gain. Require identical sample rates.

    Refuses mismatched durations > 100ms; small tails are padded with silence.
    Resampling is intentionally not hidden: it must be explicit in a later version.
    """
    if not paths:
        raise ValueError('No tracks')
    out = {}
    rate = None
    for name, path in paths.items():
        array, sample_rate = _load(Path(path))
        if rate is not None and sample_rate != rate:
            raise ValueError(f'Sample rate mismatch: {name} is {sample_rate} Hz, expected {rate} Hz. Convert sources first.')
        rate = sample_rate
        out[name] = array * float((gains or {}).get(name, 1.0))
    lengths = [len(a) for a in out.values()]
    if max(lengths) - min(lengths) > int(rate * .1):
        raise ValueError('Track durations differ by more than 100 ms. Align renders before comparing.')
    length = max(lengths)
    return {name: np.pad(a, ((0, length-len(a)),(0,0))) for name,a in out.items()}, rate


class LiveAB:
    """Continuous playback cursor; crossfade when choosing another version."""
    def __init__(self, fade_ms: float = 25):
        self.lock = threading.RLock()
        self.tracks: dict[str, np.ndarray] = {}
        self.rate = 48000
        self.cursor = 0
        self.selected = 'original'
        self.fade_previous: str | None = None
        self.fade_progress = 0
        self.fade_frames = 0
        self.fade_ms = fade_ms
        self.playing = False
        self.range_end: int | None = None
        self.stream = None

    def load(self, paths: dict[str, Path], gains: dict[str, float] | None = None):
        tracks, rate = prepare_tracks(paths, gains)
        self.close()
        with self.lock:
            self.tracks, self.rate, self.cursor = tracks, rate, 0
            self.selected = 'original' if 'original' in tracks else next(iter(tracks))
            self.fade_frames = max(1, int(rate * self.fade_ms / 1000))
            self.fade_previous = None

    @property
    def duration_ms(self) -> int:
        with self.lock:
            return round(len(next(iter(self.tracks.values()))) * 1000 / self.rate) if self.tracks else 0

    @property
    def position_ms(self) -> int:
        with self.lock:
            return round(self.cursor * 1000 / self.rate)

    def seek(self, milliseconds: int):
        with self.lock:
            length = len(next(iter(self.tracks.values()))) if self.tracks else 0
            self.cursor = min(length, max(0, round(milliseconds * self.rate / 1000)))
            self.fade_previous = None
            self.range_end = None

    def choose(self, name: str):
        with self.lock:
            if name not in self.tracks:raise KeyError(name)
            if name != self.selected:
                # Change source but never reset the playback cursor.
                self.fade_previous = self.selected
                self.selected = name
                self.fade_progress = 0

    def set_range_end(self, milliseconds: int | None):
        with self.lock:
            self.range_end = None if milliseconds is None else round(milliseconds * self.rate/1000)

    def render_block(self, frames: int) -> np.ndarray:
        """Audio callback core, testable without audio device or Qt."""
        result = np.zeros((frames,2), dtype=np.float32)
        with self.lock:
            if not self.playing or not self.tracks:return result
            limit = len(self.tracks[self.selected])
            if self.range_end is not None:limit = min(limit, self.range_end)
            n = min(frames,max(0,limit-self.cursor))
            if n:
                a = self.tracks[self.selected][self.cursor:self.cursor+n]
                result[:n] = a
                if self.fade_previous is not None and self.fade_previous in self.tracks:
                    last = self.tracks[self.fade_previous][self.cursor:self.cursor+n]
                    t = np.clip((np.arange(n) + self.fade_progress + 1) / self.fade_frames,0,1).astype('float32')[:,None]
                    result[:n] = last*(1-t)+a*t
                    self.fade_progress += n
                    if self.fade_progress >= self.fade_frames:self.fade_previous=None
                self.cursor += n
            if n < frames or self.cursor >= limit:
                self.playing=False
                self.range_end=None
        return result

    def _callback(self, outdata, frames, _time, _status):
        outdata[:] = self.render_block(frames)

    def play(self):
        if not self.tracks:raise RuntimeError('Load audio before playback')
        import sounddevice as sd
        with self.lock:
            if self.cursor >= len(self.tracks[self.selected]):self.cursor=0
            self.playing=True
        try:
            if self.stream is None:
                self.stream=sd.OutputStream(samplerate=self.rate, channels=2, dtype='float32',
                                            callback=self._callback, blocksize=1024)
                self.stream.start()
        except Exception:
            with self.lock:self.playing=False
            raise

    def pause(self):
        with self.lock:self.playing=False

    def stop(self):
        with self.lock:
            self.playing=False;self.cursor=0;self.range_end=None;self.fade_previous=None

    def close(self):
        with self.lock:self.playing=False
        if self.stream is not None:
            self.stream.stop();self.stream.close();self.stream=None
