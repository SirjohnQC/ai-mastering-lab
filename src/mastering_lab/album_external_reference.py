"""Validate a standalone local audio reference for premix guidance and master QC comparison.

Never register the reference as an album track, never overwrite it and never
send audio to Hermes. Only derived scalar metrics can enter the local prompt.
"""
from __future__ import annotations
from contextlib import contextmanager
import math
from tempfile import TemporaryDirectory
from pathlib import Path


def validate_external_reference(source):
    import soundfile as sf
    path=Path(source).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in ('.wav', '.mp3'):
        raise ValueError('The album reference must be an existing WAV or MP3 file.')
    if path.suffix.lower() == '.mp3':
        return path
    _validate_pcm(path, sf)
    return path


def _validate_pcm(path, sf):
    with sf.SoundFile(str(path)) as f:
        if f.channels!=2 or f.frames<8192 or f.samplerate<32000:
            raise ValueError('Reference needs stereo audio, >=32 kHz and enough samples.')


@contextmanager
def external_reference_pcm(source):
    """Decode MP3 only while extracting PCM features in a worker."""
    import soundfile as sf
    from .stem_mixer import decode_audio

    path = validate_external_reference(source)
    if path.suffix.lower() == '.wav':
        yield path
        return
    with TemporaryDirectory(prefix='frankenstem-album-ref-') as folder:
        pcm = decode_audio(path, Path(folder))
        _validate_pcm(pcm, sf)
        yield pcm


def external_reference_metrics(source, *, measurer=None):
    """Real EBU R128 LUFS / true peak; never infer them from sampled RMS."""
    source=validate_external_reference(source)
    if measurer is None:
        import shutil
        from .auto_master import _measure
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:
            raise RuntimeError('FFmpeg is needed to measure album reference loudness.')
        metrics=_measure(ffmpeg,source)
    else:
        metrics=measurer(source)
    try:
        lufs=float(metrics['input_i'])
        peak=float(metrics['input_tp'])
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError('Reference loudness measurement is incomplete.') from exc
    if not math.isfinite(lufs) or not math.isfinite(peak):
        raise ValueError('Reference loudness measurement is not finite.')
    return {'file':str(source),'output_lufs':lufs,'output_true_peak_dbtp':peak,
            'status':'external_reference','note':'Listening anchor only, not a certified album master.'}
