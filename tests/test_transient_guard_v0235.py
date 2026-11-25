"""v0.23.5: read-only temporal evidence, and adviser rejects extreme flattening."""
import ast
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from mastering_lab.transient_guard import compare_windows
from mastering_lab.compression_advisor import suggest_compression

ROOT = Path(__file__).resolve().parents[1]


class TransientGuardTests(unittest.TestCase):
    def test_detects_strong_loud_only_attenuation(self):
        sr = 48000
        # Alternating 200 ms loud/quiet sections, >3 seconds total.
        t = np.arange(sr*4,dtype='float64')/sr
        loud = ((np.arange(sr*4)//(sr//5))%2)==0
        original = np.sin(t*2*np.pi*300)*np.where(loud,.75,.12)
        processed = original*np.where(loud,.32,1.0)
        with tempfile.TemporaryDirectory() as folder:
            a=Path(folder)/'original.wav'
            b=Path(folder)/'processed.wav'
            sf.write(str(a),np.column_stack([original, original]).astype('float32'),sr,subtype='FLOAT')
            sf.write(str(b),np.column_stack([processed,processed]).astype('float32'),sr,subtype='FLOAT')
            result=compare_windows(a,b)
        self.assertEqual(result['status'],'measured')
        self.assertTrue(result['overcompression_warning'])
        self.assertLess(result['loud_relative_to_quiet_db'],-5.0)
        self.assertGreater(result['active_windows'],10)

    def test_identical_wavs_have_no_relative_compression(self):
        sr=48000
        t=np.arange(sr)/sr
        audio=.45*np.sin(2*np.pi*120*t)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'same.wav'
            sf.write(str(p),np.column_stack([audio,audio]).astype('float32'),sr,subtype='FLOAT')
            result=compare_windows(p,p)
        self.assertEqual(result['loud_relative_to_quiet_db'],0)
        self.assertTrue(result['effect_nearly_inaudible_warning'])
        self.assertFalse(result['overcompression_warning'])

    def test_guard_rejects_overcompressed_advisor_candidate(self):
        metrics={}
        for comp in ('original','gentle','firm'):
            metrics['balanced/'+comp]={
                'rms_dbfs':-17,'sample_peak_dbfs':-3,
                'crest_db':15 if comp=='original' else 13,
                'rms_delta_db':-1,'max_absolute_sample_difference':.4,
                'same_samples_as_original':False}
        metrics['balanced/firm']['window_analysis']={'overcompression_warning':True}
        result=suggest_compression(metrics,'balanced','punchy')
        self.assertFalse(result['candidates']['firm']['eligible'])

    def test_code_parses(self):
        for file in ('transient_guard.py','compare_visual_diagnostics.py',
                     'unified_comparison.py','compression_advisor.py'):
            ast.parse((ROOT/'src'/'mastering_lab'/file).read_text(encoding='utf-8'))


if __name__=='__main__':
    unittest.main()
