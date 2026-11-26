"""Stem Inspector v0.26.6: real DSP evidence, bypass, Dry/Wet preservation."""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from mastering_lab.stem_fx_advisor import advise_one,inspect_and_advise
from mastering_lab.stem_fx_preview import create_stem_preview
from mastering_lab.stem_mixer import config_template

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


def analysis(*, clipped=0,hf=.03,crest=12,rms=-22):
    return {'windows':[{'rms_dbfs':rms,'crest_db':crest,
                        'hf_ratio_above_10khz':hf,
                        'near_clipped_samples':clipped,
                        'nonfinite_audio':False}]}


class StemFXAdvisorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        n=48000
        x=.16*np.sin(np.arange(n)*2*np.pi*220/48000)
        self.source=self.folder/'lead_vocals.wav'
        sf.write(self.source,x,48000,subtype='PCM_24')
        self.before=self.source.read_bytes()

    def test_headroom_recommendation_not_auto_approval(self):
        x=advise_one({'group':'vocals'},analysis())
        self.assertEqual(x['status'],'candidate')
        self.assertEqual(x['recommendation'],'audition_only')
        self.assertIn('median_crest_db',x['evidence'])

    def test_high_frequency_and_near_clip_bypass(self):
        for features in (analysis(hf=.4),analysis(clipped=3)):
            x=advise_one({'group':'vocals'},features)
            self.assertEqual(x['recommendation'],'bypass')
        x=advise_one({'group':'drums'},analysis())
        self.assertEqual(x['recommendation'],'bypass')
        x=advise_one({'group':'other'},analysis())
        self.assertEqual(x['recommendation'],'bypass')

    def test_measured_inspection_does_not_enable_any_stem(self):
        config=config_template(self.folder)
        result=inspect_and_advise(config)
        self.assertEqual(len(result),1)
        self.assertFalse(result[0]['enabled'])
        self.assertEqual(result[0]['file'],str(self.source.resolve()))
        self.assertGreater(result[0]['inspection']['duration_ms'],0)
        self.assertIn(result[0]['advisor']['status'],
                      ('candidate','caution','review','quiet','insufficient_data'))

    def test_real_wet_preview_keeps_length_and_dry_source(self):
        result=create_stem_preview(
            self.source,self.folder/'cache',style='tape',drive=.4,mix=.08)
        self.assertEqual(result['status'],'audition_only')
        self.assertFalse(result.get('approved',False))
        self.assertLessEqual(abs(result['rms_difference_db']),.2)
        self.assertTrue(Path(result['file']).exists())
        with sf.SoundFile(self.source) as a, sf.SoundFile(result['file']) as b:
            self.assertEqual((a.frames,a.samplerate,a.channels),
                             (b.frames,b.samplerate,b.channels))
        self.assertEqual(self.source.read_bytes(),self.before)
        self.assertEqual(create_stem_preview(
            self.source,self.folder/'cache',style='tape',drive=.4,mix=.08)['file'],
            result['file'])

    def test_wet_louder_than_safe_peak_is_refused(self):
        def make_loud(_src,dst,**kwargs):
            sf.write(dst,np.ones(48000)*.999,48000,subtype='PCM_24')
        with self.assertRaises(ValueError):
            create_stem_preview(self.source,self.folder/'unsafe',style='tube',
                                drive=.6,mix=.2,processor=make_loud)
        self.assertFalse(list((self.folder/'unsafe').glob('fx-*.wav')))
        self.assertEqual(self.source.read_bytes(),self.before)

    def test_ui_background_threads_and_previews_wired(self):
        ui=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        for name in ('stem_fx_advisor.py','stem_fx_preview.py','album_studio_ui.py',
                     'version.py'):
            ast.parse((ROOT/name).read_text(encoding='utf-8'))
        for needle in (
            'class StemInspectWorker(QThread):',
            'class StemPreviewWorker(QThread):',
            'class StemPreviewDialog(QDialog):',
            'self.analyze_button.clicked.connect(self._analyze)',
            'self._analysis_ready',
            'self.advice_by_path',
            'self._preview(source,st,d,w)',
            "self.selection=validated_selections(self.config,selections)",
        ):
            self.assertIn(needle,ui)


if __name__=='__main__':
    unittest.main()
