"""Create safe stereo 1 kHz, -18 dBFS peak test WAV (48 kHz, 3 s)."""
import math
import wave
from array import array
from pathlib import Path

out = Path(__file__).resolve().parents[1] / "test-tone.wav"
sample_rate = 48000
samples = array("h")
for i in range(sample_rate * 3):
    value = int(32767 * 10 ** (-18 / 20) * math.sin(2 * math.pi * 1000 * i / sample_rate))
    samples.extend([value, value])
with wave.open(str(out), "wb") as wav:
    wav.setnchannels(2)
    wav.setsampwidth(2)
    wav.setframerate(sample_rate)
    wav.writeframes(samples.tobytes())
print(out)
