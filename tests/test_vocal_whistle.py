"""Regression coverage for timed narrow peaks in vocal WAV files."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from mastering_lab.vocal_whistle import scan_vocal_whistles


class VocalWhistleTests(unittest.TestCase):
    def scan(self, audio, rate, **options):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'vocals.wav'
            sf.write(path, audio, rate, subtype='FLOAT')
            return scan_vocal_whistles(path, **options)

    def test_stereo_whistle_is_localized_without_phase_cancellation(self):
        for rate in (44100, 48000):
            with self.subTest(rate=rate):
                time = np.arange(rate * 3) / rate
                voice = 0.13 * np.sin(2 * np.pi * 280 * time)
                whistle = 0.035 * np.sin(2 * np.pi * 7132 * time)
                whistle *= (time >= 0.8) & (time < 1.6)
                markers = self.scan(np.stack([voice + whistle, voice - whistle], axis=1), rate)
                self.assertEqual(len(markers), 1)
                self.assertAlmostEqual(markers[0]['hz'], 7132, delta=5)
                self.assertAlmostEqual(markers[0]['start'], 0.8, delta=0.18)
                self.assertAlmostEqual(markers[0]['end'], 1.6, delta=0.18)

    def test_ordinary_low_harmonics_and_short_high_transient_are_ignored(self):
        rate = 48000
        time = np.arange(rate * 2) / rate
        voice = sum(0.05 / h * np.sin(2 * np.pi * 220 * h * time) for h in range(1, 9))
        voice += 0.04 * np.sin(2 * np.pi * 7600 * time) * ((time >= .8) & (time < .84))
        self.assertEqual(self.scan(voice, rate), [])

    def test_cancelled_analysis_returns_no_markers(self):
        self.assertEqual(self.scan(np.zeros(16000), 48000, cancelled=lambda: True), [])
