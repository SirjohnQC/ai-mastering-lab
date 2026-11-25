"""DSP-unit tests run without Qt or the Windows plugin."""
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

MODULE = Path(__file__).resolve().parents[1] / 'src/mastering_lab/pro_c3_loudness_match.py'
spec = importlib.util.spec_from_file_location('pro_c3_loudness_match', MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PlaybackMatchingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        sr = 48000
        # Four blocks: silent, loud, quiet, loud. Exact length not required.
        t = np.arange(48000 * 2, dtype=np.float64) / sr
        self.signal = (0.15 * np.sin(2 * np.pi * 440 * t)).astype('float32')

    def write(self, name, mul, extra=0):
        path = self.base / name
        audio = np.column_stack([self.signal * mul] * 2)
        if extra:
            audio = np.concatenate([audio, np.ones((extra, 2), dtype='float32') * .99])
        sf.write(path, audio, 48000, subtype='FLOAT')
        return path

    def test_matching_attenuation_only(self):
        paths = {'original': self.write('original.wav', 1.0),
                 'gentle': self.write('gentle.wav', .75),
                 'firm': self.write('firm.wav', .4)}
        out = m.build_playback_matching(paths, source_frames=len(self.signal))
        self.assertEqual('ready', out['status'])
        self.assertEqual(0, out['gain_db']['firm'])
        self.assertAlmostEqual(-7.959, out['gain_db']['original'], delta=.02)
        self.assertTrue(all(-18 <= x <= 0 for x in out['gain_db'].values()))
        normalized = [out['level_dbfs'][k] + out['gain_db'][k] for k in paths]
        self.assertLess(max(normalized) - min(normalized), .02)

    def test_ignores_tail(self):
        path = self.write('tail.wav', .5, extra=64)
        normal = self.write('normal.wav', .5)
        a = m.active_rms_dbfs(path, source_frames=len(self.signal))
        b = m.active_rms_dbfs(normal, source_frames=len(self.signal))
        self.assertEqual(a, b)

    def test_rejects_wrong_dimensions(self):
        p = self.base / 'mono.wav'
        sf.write(p, self.signal, 48000)
        with self.assertRaises(ValueError):
            m.active_rms_dbfs(p, source_frames=len(self.signal))

    def test_silent_rejected(self):
        p = self.base / 'silence.wav'
        sf.write(p, np.zeros((96000,2), dtype='float32'), 48000)
        self.assertIsNone(m.active_rms_dbfs(p, source_frames=96000))

    def test_clamps_18_db(self):
        paths = {'original': self.write('a.wav', 1),
                 'gentle': self.write('b.wav', .5),
                 'firm': self.write('c.wav', .01)}
        result = m.build_playback_matching(paths, source_frames=len(self.signal))
        self.assertEqual('limited', result['status'])
        self.assertEqual(-18, result['gain_db']['original'])

    def test_output_volume_safe(self):
        paths = {'original': self.write('a.wav', 1),
                 'gentle': self.write('b.wav', .8),
                 'firm': self.write('c.wav', .5)}
        match = m.build_playback_matching(paths, source_frames=len(self.signal))
        self.assertLess(m.preview_volume(match,'original', True), m.preview_volume(match,'firm', True))
        self.assertEqual(m.BASE_VOLUME, m.preview_volume(match,'original', False))
        with self.assertRaises(ValueError):
            m.preview_volume(match, 'random', True)

    def test_no_wav_modification(self):
        paths = {'original': self.write('a.wav', 1),
                 'gentle': self.write('b.wav', .8),
                 'firm': self.write('c.wav', .5)}
        before = {k: p.read_bytes() for k, p in paths.items()}
        m.build_playback_matching(paths, source_frames=len(self.signal))
        self.assertEqual(before, {k: p.read_bytes() for k, p in paths.items()})

    def test_gui_shutdown_and_heart_still_present(self):
        text = (MODULE.parent / 'pro_c3_song_preview_ui.py').read_text(encoding='utf8')
        for part in ('self.dialog.before_close = self._shutdown_audio',
                     'self.player.setSource(QUrl())', 'self.player.setAudioOutput(None)',
                     'self._update_hearts()', 'self.match_checkbox.toggled.connect(self._apply_playback_level)',
                     'self.output.setVolume(volume)'):
            self.assertIn(part, text)

if __name__ == '__main__': unittest.main()
