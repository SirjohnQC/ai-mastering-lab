import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.release_preflight import analyze_wav, format_preflight, PreflightError


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'my-master.wav'

    def write(self, data, sr=48000, subtype='PCM_24'):
        sf.write(self.path, data, sr, subtype=subtype)

    def test_clean_file_unchanged_and_report_written(self):
        t = np.arange(48000 * 11) / 48000
        a = .25 * np.sin(2 * np.pi * 440 * t)
        self.write(np.column_stack((a, a)))
        before = self.path.read_bytes()
        report = analyze_wav(self.path, measure_loudness=lambda p: {'input_i': '-14.1', 'input_tp': '-1.2', 'input_lra': '3.3'})
        self.assertEqual(report['status'], 'technical_pass')
        self.assertFalse(report['publication_approved'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(json.loads(Path(report['report_path']).read_text(encoding='utf-8'))['kind'], 'release_preflight')
        self.assertIn('Spotify', format_preflight(report))

    def test_wavex_stereo_pcm24_is_valid(self):
        # WAVEX is an ordinary WAVE_FORMAT_EXTENSIBLE WAV that libsndfile labels WAVEX.
        t = np.arange(48000 * 11) / 48000
        a = .25 * np.sin(2 * np.pi * 440 * t)
        sf.write(self.path, np.column_stack((a, a)), 48000,
                 format='WAVEX', subtype='PCM_24')
        report = analyze_wav(self.path, measure_loudness=lambda p: {
            'input_i': '-14.02', 'input_tp': '-0.97', 'input_lra': '3.3'},
            write_report=False)
        self.assertEqual(report['file']['format'], 'WAVEX')
        self.assertEqual(report['file']['channels'], 2)
        self.assertEqual(report['status'], 'technical_pass_with_notes')
        self.assertFalse(any('stéréo' in x or 'Conteneur' in x for x in report['issues']))
        self.assertTrue(any('True peak' in x for x in report['warnings']))

    def test_wavex_mono_still_rejected(self):
        sf.write(self.path, np.zeros(48000 * 11), 48000,
                 format='WAVEX', subtype='PCM_24')
        report = analyze_wav(self.path, write_report=False)
        self.assertTrue(any('2 canaux stéréo' in x for x in report['issues']))

    def test_clipped_signal_needs_review(self):
        self.write(np.ones((48000 * 11, 2)))
        r = analyze_wav(self.path, measure_loudness=lambda p: {'input_i': '-3', 'input_tp': '0', 'input_lra': '0'}, write_report=False)
        self.assertEqual(r['status'], 'needs_review')
        self.assertGreater(r['audio']['clipped_frames'], 0)

    def test_mono_rejected_in_report(self):
        self.write(np.zeros(48000 * 11))
        r = analyze_wav(self.path, write_report=False)
        self.assertEqual(r['status'], 'needs_review')
        self.assertTrue(any('stéréo' in x for x in r['issues']))

    def test_silence_detected(self):
        self.write(np.zeros((48000 * 11, 2)))
        r = analyze_wav(self.path, write_report=False)
        self.assertEqual(r['status'], 'needs_review')
        self.assertTrue(any('silencieux' in x for x in r['issues']))

    def test_loudness_measure_failure_needs_review(self):
        self.write(np.full((48000 * 11, 2), .1))
        def broken(p):
            raise RuntimeError('ffmpeg error')
        r = analyze_wav(self.path, measure_loudness=broken, write_report=False)
        self.assertEqual(r['status'], 'needs_review')

    def test_missing_path(self):
        with self.assertRaises(PreflightError):
            analyze_wav(self.path)

    def test_ui_hook_is_on_master_page(self):
        src = (Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab' / 'auto_studio_ui.py').read_text()
        self.assertIn('self.master_preflight.clicked.connect(self._run_release_preflight)', src)
        self.assertIn('self.master_preflight.show()', src)
        self.assertIn('ReleasePreflightWorker(output, self)', src)


if __name__ == '__main__':
    unittest.main()
