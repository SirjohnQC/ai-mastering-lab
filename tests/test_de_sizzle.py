import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

from mastering_lab.de_sizzle import scan_sizzle, render_passages


class DeSizzleTests(unittest.TestCase):
    def test_broad_burst_is_localized_and_gently_reduced(self):
        rate = 48000
        t = np.arange(2 * rate) / rate
        tone = 0.1 * np.sin(2 * np.pi * 200 * t)
        noise = sosfilt(butter(6, [5200, 10800], 'bandpass', fs=rate, output='sos'),
                        np.random.default_rng(42).normal(size=t.size))
        burst = (t >= 0.55) & (t < 1.35)
        samples = tone + burst * 0.08 * noise
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'voice.wav'
            corrected = Path(folder) / 'wet.wav'
            sf.write(source, np.column_stack([samples, -samples]), rate, subtype='FLOAT')
            original = source.read_bytes()
            markers = scan_sizzle(source)
            self.assertEqual(len(markers), 1)
            self.assertAlmostEqual(markers[0]['start'], 0.55, delta=0.13)
            self.assertAlmostEqual(markers[0]['end'], 1.35, delta=0.09)
            self.assertLessEqual(markers[0]['match_db'], 1)
            render_passages(source, corrected, markers)
            output, actual_rate = sf.read(corrected)
            self.assertEqual(actual_rate, rate)
            self.assertEqual(output.shape, (len(samples), 2))
            self.assertEqual(source.read_bytes(), original)
            inside = (t > 0.8) & (t < 1.1)
            self.assertLess(np.std(output[inside, 0] - tone[inside]),
                            0.85 * np.std(samples[inside] - tone[inside]))
            outside = (t < markers[0]['start']) | (t >= markers[0]['end'])
            np.testing.assert_array_equal(output[outside, 0], samples[outside].astype('float32'))

    def test_narrow_whistle_is_not_a_broad_burst(self):
        rate = 48000
        t = np.arange(rate) / rate
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'whistle.wav'
            sf.write(source, 0.1 * np.sin(2 * np.pi * 7500 * t), rate)
            self.assertEqual(scan_sizzle(source), [])
