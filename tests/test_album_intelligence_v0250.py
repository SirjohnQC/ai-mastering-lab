"""v0.25.0: album reference comparison from synthetic, local QC WAVs."""
from __future__ import annotations
import ast
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from mastering_lab.album_intelligence import compare_album, spectrum_profile

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'


def make_track(directory, label, frequency, lufs, tp, *, pass_qc=True):
    rate = 48000
    t = np.arange(rate*3, dtype='float64') / rate
    signal = (np.sin(2*np.pi*frequency*t)*0.3).astype('float32')
    path = directory / (label+'.wav')
    sf.write(str(path),np.column_stack([signal, signal]),rate,subtype='PCM_24')
    status = 'qc_pass' if pass_qc else 'needs_review'
    return {'path':str(path),'title':label,'kind':'stereo','status':status,
            'result':{'status':status,'file':str(path),
                      'output_lufs':lufs,'output_true_peak_dbtp':tp}}


class AlbumIntelligenceTests(unittest.TestCase):
    def test_identical_masters_have_no_spectral_difference(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            first=make_track(root,'ref',220,-14.0,-1.2)
            second=make_track(root,'second',220,-14.2,-1.1)
            result=compare_album({'album':'Test','tracks':[first,second]},
                                 reference_index=0)
            self.assertEqual(result['reference_index'],0)
            self.assertEqual(result['tracks'][0]['status'],'reference')
            self.assertEqual(result['tracks'][1]['lufs_delta'],-0.2)
            self.assertTrue(all(abs(v)<0.05 for v in
                                result['tracks'][1]['relative_band_delta_db']))
            self.assertFalse(result['tracks'][1]['flags'])

    def test_different_frequency_triggers_listening_review_not_processing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            tracks=[make_track(root,'bass',180,-14.0,-1.1),
                    make_track(root,'treble',5400,-14.1,-1.1)]
            result=compare_album({'tracks':tracks},reference_index=0)
            self.assertIn('spectrum_review',result['tracks'][1]['flags'])
            self.assertTrue(Path(tracks[1]['result']['file']).is_file())

    def test_unfinished_tracks_are_not_mistaken_for_approved_masters(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            tracks=[make_track(root,'ref',220,-14.0,-1.2),
                    make_track(root,'failed',220,-14,-.5,pass_qc=False)]
            report=compare_album({'tracks':tracks},reference_index=0)
            self.assertEqual(report['tracks'][1]['status'],'not_ready')
            with self.assertRaises(ValueError):
                compare_album({'tracks':tracks},reference_index=1)

    def test_missing_master_wav_is_ineligible(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            valid=make_track(root,'ref',220,-14,-1.2)
            missing=dict(valid)
            missing['result']=dict(valid['result'],file=str(root/'missing.wav'))
            with self.assertRaises(ValueError):
                compare_album({'tracks':[missing]},reference_index=0)

    def test_ui_wiring_and_code_parse(self):
        for module in ('album_intelligence.py','album_studio_ui.py'):
            ast.parse((ROOT/module).read_text(encoding='utf-8'))
        ui=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('self.compare_album_btn.clicked.connect(self._analyze_album)',ui)
        self.assertIn('AlbumIntelligenceWorker(',ui)
        self.assertIn("self.export_dir / 'album_consistency.json'",ui)
        self.assertIn('self.project[\'reference_source\']',ui)
        self.assertIn('self._intelligence_worker.wait(5000)',ui)


if __name__=='__main__':
    unittest.main()
