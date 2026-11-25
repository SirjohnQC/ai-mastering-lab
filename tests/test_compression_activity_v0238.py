"""v0.23.8 threshold-occupancy input inspection regression tests."""
from __future__ import annotations
import ast
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from mastering_lab.compression_activity import inspect_threshold_activity, interpret_activity

ROOT = Path(__file__).resolve().parents[1]


def write_wav(path, values):
    samples = np.asarray(values,dtype='float32')
    sf.write(str(path),np.column_stack([samples,samples]),48000,subtype='FLOAT')


class CompressorActivityTests(unittest.TestCase):
    def test_brief_single_peak_is_not_a_sustained_rms_crossing(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'brief.wav'
            audio=np.full(48000,.02,dtype='float32')
            audio[10000:10004]=.8
            write_wav(path,audio)
            result=inspect_threshold_activity(path,-9.)
        self.assertEqual(result['status'],'measured')
        self.assertGreater(result['peak_above_threshold_pct'],0)
        self.assertEqual(result['rms_above_threshold_pct'],0)
        self.assertLessEqual(result['longest_peak_run_ms'],10)
        self.assertEqual(interpret_activity(result,-.002)['status'],'brief_peaks')

    def test_sustained_high_level_is_observed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sustained.wav'
            samples=np.zeros(48000,dtype='float32')
            samples[10000:34000]=.6
            write_wav(path,samples)
            result=inspect_threshold_activity(path,-9.)
        self.assertGreater(result['peak_above_threshold_pct'],30.)
        self.assertGreater(result['rms_above_threshold_pct'],30.)
        self.assertGreaterEqual(result['longest_rms_run_ms'],300)
        self.assertEqual(interpret_activity(result,-.003)['status'],'sustained_input')

    def test_below_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'quiet.wav'
            write_wav(path,np.full(48000,.02,dtype='float32'))
            result=inspect_threshold_activity(path,-9.)
        self.assertEqual(result['peak_above_threshold_pct'],0)
        self.assertEqual(interpret_activity(result,0)['status'],'below_threshold')

    def test_unsupported_unreadable_threshold_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.wav'
            write_wav(path,np.full(48000,.02,dtype='float32'))
            result=inspect_threshold_activity(path,None)
        self.assertEqual(result['status'],'unavailable')
        with self.assertRaises(ValueError):
            inspect_threshold_activity(path,float('nan'))

    def test_ui_and_worker_wiring_keeps_approval_manual(self):
        ui=(ROOT/'src/mastering_lab/unified_comparison.py').read_text(encoding='utf-8')
        module=ast.parse(ui)
        methods={n.name:ast.get_source_segment(ui,n) for n in ast.walk(module)
                 if isinstance(n,ast.FunctionDef)}
        self.assertIn("cache.get('diagnostics_version') == 4",ui)
        self.assertIn("inspect_threshold_activity(original, threshold_db)",ui)
        self.assertIn("_threshold_from_report(session_report, comp)",ui)
        self.assertIn('self.activity_inspector.setText(',methods['_update_active_diagnostics'])
        self.assertIn('self._approved',methods['master_source'])
        self.assertNotIn('self.approve(', methods['_update_active_diagnostics'])


if __name__=='__main__':
    unittest.main()
