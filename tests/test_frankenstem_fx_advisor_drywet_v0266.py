"""v0.26.6: real local stem analysis and independent aligned A/B audition."""
from __future__ import annotations
import ast
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf
from mastering_lab.stem_fx_advisor import inspect_stem_for_fx, inspect_config_for_fx
from mastering_lab.stem_fx_preview import prepare_stem_ab_preview
from mastering_lab.stem_mixer import config_template

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


def wav(path, *, rate=48000, seconds=3, peak=.17, mono=False):
    t=np.arange(rate*seconds,dtype='float64')/rate
    # Nontrivial crest factor; finite and comfortably below full scale.
    data=peak*(np.sin(2*np.pi*350*t)+.42*np.sin(2*np.pi*1180*t))
    sf.write(path,data if mono else np.column_stack((data,data)),
             rate,subtype='PCM_24')


class StemFxAdvisorPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.folder=self.root/'song_stems'
        self.folder.mkdir()
        self.voice=self.folder/'lead_vocals.wav'
        self.drums=self.folder/'drums.wav'
        self.bass=self.folder/'bass.wav'
        wav(self.voice,mono=True)
        wav(self.drums)
        wav(self.bass)
        self.before=self.voice.read_bytes()

    def test_fx_advisor_examines_audio_and_is_not_fake_ai_detection(self):
        a=inspect_stem_for_fx(self.voice,group='vocals')
        self.assertEqual(a['group'],'vocals')
        self.assertGreater(a['metrics']['sampled_windows'],0)
        self.assertIn(a['decision'],('audition','bypass'))
        if a['decision']=='audition':
            self.assertIn(a['suggestion']['style'],('tape','tube','softclip'))
        d=inspect_stem_for_fx(self.drums,group='drums')
        self.assertEqual(d['decision'],'bypass')
        self.assertIsNone(d['suggestion'])
        self.assertEqual(self.voice.read_bytes(),self.before)

    def test_inspect_every_stem_without_enabling_any_fx(self):
        config=config_template(self.folder)
        report=inspect_config_for_fx(config)
        self.assertEqual(len(report),len(config['tracks']))
        self.assertEqual({Path(x['file']).name for x in report},
                         {'lead_vocals.wav','drums.wav','bass.wav'})
        self.assertNotIn('enabled',report[0])
        self.assertTrue(all('metrics' in row for row in report))

    def test_preview_creates_aligned_dry_and_wet_copies(self):
        report=prepare_stem_ab_preview(
            self.voice,self.root/'cache',style='tape',drive=.5,mix=.1)
        a=Path(report['dry'])
        b=Path(report['wet'])
        self.assertTrue(a.is_file() and b.is_file())
        with sf.SoundFile(str(a)) as dry, sf.SoundFile(str(b)) as wet:
            self.assertEqual((dry.frames,dry.samplerate,dry.channels),
                             (wet.frames,wet.samplerate,wet.channels))
            self.assertEqual(dry.channels,1)
            x=dry.read(dtype='float64')
            y=wet.read(dtype='float64')
        self.assertGreater(float(np.max(np.abs(x-y))),1e-6)
        db=20*np.log10(np.sqrt(np.mean(x*x))/np.sqrt(np.mean(y*y)))
        self.assertLessEqual(abs(float(db)),.25)
        self.assertTrue(report['rms_matched'])
        self.assertEqual(self.voice.read_bytes(),self.before)
        cached=prepare_stem_ab_preview(
            self.voice,self.root/'cache',style='tape',drive=.5,mix=.1)
        self.assertEqual(report,cached)

    def test_settings_change_generates_a_distinct_local_preview(self):
        a=prepare_stem_ab_preview(
            self.voice,self.root/'cache',style='tape',drive=.4,mix=.1)
        b=prepare_stem_ab_preview(
            self.voice,self.root/'cache',style='tube',drive=.4,mix=.1)
        self.assertNotEqual(a['wet'],b['wet'])
        self.assertEqual(self.voice.read_bytes(),self.before)

    def test_preview_bad_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            prepare_stem_ab_preview(
                self.voice,self.root/'cache',style='invalid',drive=.8,mix=.1)

    def test_ui_is_backgrounded_and_does_not_auto_enable_stems(self):
        for name in ('stem_fx_ui.py','stem_fx_advisor.py','stem_fx_preview.py',
                     'album_studio_ui.py','version.py'):
            ast.parse((ROOT/name).read_text(encoding='utf-8'))
        ui=(ROOT/'stem_fx_ui.py').read_text(encoding='utf-8')
        album=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        for phrase in (
            'class FxScanWorker(QThread):',
            'class FxPreviewWorker(QThread):',
            'class StemDryWetDialog(QDialog):',
            'class StemFxSurgeryDialog(QDialog):',
            "self.worker.start()",
            "self.analyze_btn.clicked.connect(self._analyze)",
            'preview.clicked.connect(lambda _,n=i:self._preview(n))',
            'self._approve',
            "self.a_player=QMediaPlayer(self)",
            "self.b_player=QMediaPlayer(self)",
            'self._highlight()',
        ):
            self.assertIn(phrase,ui)
        self.assertNotIn("row['check'].setChecked(True)",ui)
        self.assertIn('dialog=StemFxSurgeryDialog(',album)
        self.assertIn("track['stem_saturation']=dialog.selection",album)


if __name__=='__main__':
    unittest.main()
