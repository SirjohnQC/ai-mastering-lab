"""v0.23.2 regression: real WAV metrics, waveform routing and manual mastering gate."""
from pathlib import Path
import ast
import tempfile
import unittest

import numpy as np
import soundfile as sf

from mastering_lab.compare_visual_diagnostics import measure_combinations

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / 'src/mastering_lab/unified_comparison.py').read_text(encoding='utf-8')


class CompressionDisplayTests(unittest.TestCase):
    def test_all_nine_variants_are_measured_and_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            sample = np.linspace(0, 2 * np.pi * 24, 4096, dtype=np.float64)
            source = (0.82 * np.sin(sample)).astype('float32')
            files = {}
            for mix_index, mix in enumerate(('balanced','vocal-focus','punchy')):
                for comp in ('original','gentle','firm'):
                    # Test samples are synthetic, not expected Pro-C outputs.
                    factor = {'original':1.0,'gentle':0.85,'firm':0.55}[comp]
                    stereo = np.stack([source * factor, source * factor * (0.9-mix_index*0.08)], axis=1)
                    path = folder / (mix + '_' + comp + '.wav')
                    sf.write(str(path), stereo, 48000, subtype='FLOAT')
                    files[mix,comp] = path
            result = measure_combinations(files)
            self.assertEqual(len(result['envelopes']), 9)
            self.assertEqual(len(result['metrics']), 9)
            self.assertFalse(result['metrics']['balanced/firm']['same_samples_as_original'])
            self.assertLess(result['metrics']['balanced/firm']['rms_delta_db'], -3)
            a = result['envelopes']['balanced/original']
            b = result['envelopes']['balanced/firm']
            self.assertNotEqual(a, b)

    def test_identical_files_trigger_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            files = {}
            audio = np.zeros((512,2), dtype='float32')
            audio[10:250,:] = .15
            for mix in ('balanced','vocal-focus','punchy'):
                for comp in ('original','gentle','firm'):
                    path = folder / (mix + comp + '.wav')
                    sf.write(str(path), audio, 48000, subtype='FLOAT')
                    files[mix,comp] = path
            result = measure_combinations(files)
            self.assertTrue(result['metrics']['balanced/firm']['same_samples_as_original'])
            self.assertTrue(any('EXACT same samples' in w for w in result['warnings']))

    def test_switch_refreshes_active_metrics_without_restarting(self):
        mod = ast.parse(UI)
        methods = {n.name:ast.get_source_segment(UI,n) for n in ast.walk(mod)
                   if isinstance(n, ast.FunctionDef)}
        self.assertIn('self._update_active_diagnostics()', methods['_switch'])
        self.assertIn('self.waveform.setData(np.asarray(wave', methods['_update_active_diagnostics'])
        self.assertIn('self._approved', methods['master_source'])
        for disallowed in ('.play(', '.stop(', '.setSource('):
            self.assertNotIn(disallowed, methods['_switch'])

    def test_full_source_compiles(self):
        for path in ('src/mastering_lab/unified_comparison.py',
                     'src/mastering_lab/compare_visual_diagnostics.py',
                     'src/mastering_lab/version.py'):
            ast.parse((ROOT/path).read_text(encoding='utf-8'))

if __name__ == '__main__':
    unittest.main()
