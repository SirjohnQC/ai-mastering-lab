"""Validate a standalone local WAV reference for premix guidance and master QC comparison.

Never register the reference as an album track, never overwrite it and never
send audio to Hermes. Only derived scalar metrics can enter the local prompt.
"""
from __future__ import annotations
import math
from pathlib import Path


def validate_external_reference(source):
    import soundfile as sf
    path=Path(source).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower()!='.wav':
        raise ValueError('The album reference must be an existing WAV file.')
    with sf.SoundFile(str(path)) as f:
        if f.channels!=2 or f.frames<8192 or f.samplerate<32000:
            raise ValueError('Reference needs stereo audio, >=32 kHz and enough samples.')
    return path


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
