"""Compare WAVs using standard-library RMS. Handles PCM16/PCM24 files."""
from pathlib import Path
import sys, wave, math

def stats(path):
    with wave.open(str(path), "rb") as w:
        channels, width, sample_rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if width not in (2, 3):
            raise SystemExit("Only 16/24-bit PCM WAV supported for comparison")
        raw = w.readframes(frames)
    stride = channels * width
    acc = 0.0
    peak = 0.0
    n = 0
    # Sample every tenth frame; quick validation rather than comprehensive QC.
    for i in range(0, len(raw) - stride + 1, stride * 10):
        v = int.from_bytes(raw[i:i+width], "little", signed=True) / (2 ** (8 * width - 1))
        acc += v*v; peak = max(peak, abs(v)); n += 1
    rms = math.sqrt(acc / n) if n else 0
    return {"sample_rate":sample_rate, "frames":frames, "channels":channels,
            "rms_dbfs":20 * math.log10(max(rms,1e-12)),
            "sample_peak_dbfs":20 * math.log10(max(peak,1e-12))}

if len(sys.argv) != 3:
    raise SystemExit("Usage: python scripts/compare_wavs.py INPUT.wav OUTPUT.wav")
a, b = stats(Path(sys.argv[1])), stats(Path(sys.argv[2]))
print("Input:", a)
print("Output:", b)
print("RMS change (dB):", round(b["rms_dbfs"] - a["rms_dbfs"], 3))
