"""v0.25.2: existing master recognition is strict and never re-encodes audio."""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from mastering_lab.existing_master_import import ExistingMasterError, recognize_master

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


class ExistingMasterImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wav=Path(self.tmp.name)/'finished-master.wav'
        self.wav.write_bytes(b'non-audio synthetic marker; readers mocked')
        self.meta={'sample_rate':48000,'channels':2,'frames':48000,'subtype':'PCM_24'}
        self.qc={'status':'qc_pass','file':str(self.wav.resolve()),
                 'output':self.meta,'output_lufs':-14.01,
                 'output_true_peak_dbtp':-1.18,'target_true_peak_dbtp':-1.0}
        self.sidecar=self.wav.with_suffix('.qc.json')
        self.sidecar.write_text(json.dumps(self.qc),encoding='utf-8')

    def recognize(self, *, lufs=-14.02,peak=-1.17):
        return recognize_master(self.wav,
            measurement_fn=lambda _:{'input_i':str(lufs),'input_tp':str(peak)},
            probe_fn=lambda _:dict(self.meta))

    def test_valid_qc_sidecar_recognized(self):
        result=self.recognize()
        self.assertEqual(result['status'],'qc_pass')
        self.assertEqual(result['album_import_verification'],'independent_ffmpeg_qc_v1')
        self.assertAlmostEqual(result['output_true_peak_dbtp'],-1.17)
        self.assertEqual(self.wav.read_bytes(),
                         b'non-audio synthetic marker; readers mocked')

    def test_missing_qc_sidecar_never_automatically_approved(self):
        self.sidecar.unlink()
        with self.assertRaisesRegex(ExistingMasterError,'No matching'):
            self.recognize()

    def test_wrong_file_or_report_status_refused(self):
        self.qc['file']=str(self.wav.with_name('different.wav'))
        self.sidecar.write_text(json.dumps(self.qc),encoding='utf-8')
        with self.assertRaisesRegex(ExistingMasterError,'different WAV'):
            self.recognize()
        self.qc['file']=str(self.wav)
        self.qc['status']='needs_review'
        self.sidecar.write_text(json.dumps(self.qc),encoding='utf-8')
        with self.assertRaisesRegex(ExistingMasterError,'does not indicate a pass'):
            self.recognize()

    def test_changed_wav_metrics_refused(self):
        with self.assertRaisesRegex(ExistingMasterError,'no longer matches'):
            self.recognize(lufs=-12.9)

    def test_truepeak_above_ceiling_refused_even_if_report_claims_pass(self):
        self.qc['output_true_peak_dbtp']=-0.97
        self.sidecar.write_text(json.dumps(self.qc),encoding='utf-8')
        with self.assertRaisesRegex(ExistingMasterError,'fails acceptance'):
            self.recognize(peak=-0.97)

    def test_metadata_mismatch_refused(self):
        self.meta['frames']=30000
        with self.assertRaisesRegex(ExistingMasterError,'WAV changed since QC'):
            self.recognize()

    def test_qt_ui_scans_without_remastering(self):
        path=ROOT/'album_studio_ui.py'
        code=path.read_text(encoding='utf-8')
        ast.parse(code)
        self.assertIn("self.import_master_btn.clicked.connect(self._recognize_existing)",code)
        self.assertIn("result=recognize_master(path)",code)
        self.assertIn("result['album_source_signature']=source_signature(path,'stereo')",code)
        self.assertIn("track['status']='qc_pass'",code)
        self.assertIn("track['status']='waiting'",code)
        model=(ROOT/'existing_master_import.py').read_text(encoding='utf-8')
        ast.parse(model)
        for forbidden in ('master_song(', 'ffmpeg -y', 'sf.write(', 'replace(source', 'urlopen('):
            self.assertNotIn(forbidden,model)


if __name__=='__main__':
    unittest.main()
