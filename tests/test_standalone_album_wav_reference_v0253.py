"""v0.25.3: standalone WAV guide, separate from stems and album track list."""
from __future__ import annotations
import ast
import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf

from mastering_lab.album_external_reference import validate_external_reference, external_reference_metrics
from mastering_lab.album_intelligence import compare_album
from mastering_lab.album_match_advisor import advise_album
from mastering_lab.album_stem_pipeline import can_reuse_master, source_signature
from mastering_lab.album_mix_evaluation import choose_candidate

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


def wav(path, hz=440, rate=48000):
    times=np.arange(rate,dtype='float64')/rate
    signal=(.23*np.sin(2*np.pi*hz*times)).astype('float32')
    sf.write(str(path),np.column_stack((signal,signal)),rate,subtype='PCM_24')
    return path


class StandaloneAlbumReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.reference=wav(self.root/'outside-reference.wav',220)
        self.master=wav(self.root/'album-master.wav',300)

    def test_separate_reference_needs_no_stems_or_sidecar(self):
        self.assertEqual(validate_external_reference(self.reference),self.reference.resolve())
        self.assertFalse(self.reference.with_suffix('.qc.json').exists())
        measures=external_reference_metrics(self.reference,
            measurer=lambda _: {'input_i':-13.6,'input_tp':-1.3})
        self.assertEqual(measures['status'],'external_reference')

    def test_final_master_analysis_against_reference_outside_album(self):
        project={'album':'Demo','tracks':[{
            'path':str(self.master),'title':'My album song','kind':'stereo','status':'qc_pass',
            'result':{'status':'qc_pass','file':str(self.master),
                      'output_lufs':-14.0,'output_true_peak_dbtp':-1.2}}]}
        def profile(_):
            return {'band_shares':[.2]*5}
        out=compare_album(project,external_reference_wav=self.reference,profile_fn=profile,
                          external_measure_fn=lambda _: {'input_i':-13.6,'input_tp':-1.3})
        self.assertIsNone(out['reference_index'])
        self.assertEqual(out['reference_kind'],'standalone_wav')
        self.assertEqual(len(out['tracks']),1)
        self.assertEqual(out['tracks'][0]['status'],'measured')
        self.assertAlmostEqual(out['tracks'][0]['lufs_delta'],-.4)
        self.assertEqual(len(advise_album(out)['tracks']),1)

    def test_reference_is_weak_premix_input_not_a_track_to_render(self):
        paths={name:wav(self.root/(name+'.wav'),220)
               for name in ('balanced','vocal-focus','punchy')}
        def analyzer(_):
            return {name: {'sample_peak_clipped':False,'sample_peak_dbfs':-7.,
                           'stereo_correlation':.9,'rms_dbfs':-20.,'crest_db':13.,
                           'sample_rate':48000,'duration_seconds':1.0}
                    for name in paths}
        selected,report=choose_candidate(paths,analyzer=analyzer,
            ask_fn=lambda metrics: {'selected':'balanced','reason':'Conservative metrics.'},
            external_reference_wav=self.reference)
        self.assertEqual(selected,'balanced')
        self.assertTrue(report['reference_used'])
        self.assertEqual(report['reference_kind'],'album_standalone_wav')
        self.assertEqual(report['reference']['source_kind'],'album_standalone_wav')
        self.assertEqual(len(paths),3)
        self.assertFalse('source' in report['reference'])

    def test_external_reference_change_invalidates_stem_cache(self):
        stem_dir=self.root/'stems'
        stem_dir.mkdir()
        wav(stem_dir/'guitar.wav',120)
        wav(stem_dir/'vocal.wav',250)
        master_path=wav(self.root/'cached-master.wav',450)
        ref2=wav(self.root/'new-reference.wav',320)
        from mastering_lab.album_stem_pipeline import PIPELINE_ID
        result={'status':'qc_pass','file':str(master_path),
                'album_source_signature':source_signature(stem_dir,'stems'),
                'album_pipeline':PIPELINE_ID,
                'album_external_reference_path':str(self.reference),
                'album_external_reference_signature':source_signature(self.reference,'stereo'),
                'album_candidates':{name:str(master_path)
                                    for name in ('balanced','vocal-focus','punchy')}}
        row={'kind':'stems','status':'qc_pass','path':str(stem_dir),'result':result}
        self.assertTrue(can_reuse_master(row,external_reference_wav=self.reference))
        self.assertFalse(can_reuse_master(row,external_reference_wav=ref2))
        self.assertFalse(can_reuse_master(row,external_reference_wav=None))

    def test_ui_wiring_and_syntax(self):
        for module in ('album_external_reference.py','album_studio_ui.py',
                       'album_intelligence.py','album_match_advisor.py',
                       'album_mix_evaluation.py','album_stem_pipeline.py'):
            ast.parse((ROOT/module).read_text(encoding='utf-8'))
        ui=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('self.external_ref_select.clicked.connect(self._choose_external_reference)',ui)
        self.assertIn("self.project['external_reference_wav']=str(path)",ui)
        self.assertIn('external_reference_wav=str(external) if external else None',ui)
        self.assertIn('external_reference_wav=self.external_reference_wav',ui)
        self.assertIn('self._external_reference()',ui)


if __name__=='__main__':
    unittest.main()
