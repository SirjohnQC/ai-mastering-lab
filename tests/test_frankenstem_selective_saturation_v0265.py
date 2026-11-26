"""v0.26.5 FRANKENSTEM: only explicitly selected stems receive wet prints."""
from __future__ import annotations

import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from mastering_lab.stem_mixer import config_template
from mastering_lab.stem_saturation import (
    suggestions, validated_selections, prepare_selected_stems, selection_signature
)
from mastering_lab.album_stem_pipeline import can_reuse_master, source_signature, PIPELINE_ID

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


def wav(path, mono=False):
    rate=48000
    t=np.arange(rate,dtype=np.float64)/rate
    signal=.15*np.sin(2*np.pi*250*t)
    sf.write(str(path), signal if mono else np.column_stack((signal,signal)),
             rate, subtype='PCM_24')


class SelectiveStemSaturationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'stems'
        self.folder.mkdir()
        wav(self.folder/'lead_vocals.wav',mono=True)
        wav(self.folder/'drums.wav')
        wav(self.folder/'bass.wav')
        self.config=config_template(self.folder)
        self.hints=suggestions(self.config)

    def test_suggestions_are_all_disabled_including_drums(self):
        self.assertEqual(len(self.hints),3)
        self.assertTrue(all(item['enabled'] is False for item in self.hints))
        self.assertTrue(any(item['group']=='vocals' for item in self.hints))
        self.assertTrue(any(item['group']=='drums' for item in self.hints))

    def test_no_optin_means_no_processing(self):
        with patch('mastering_lab.album_saturation_preview.process_saturation_wav') as render:
            prepared,reports=prepare_selected_stems(
                self.config,{},Path(self.temp.name)/'dry')
        self.assertEqual(prepared,{})
        self.assertEqual(reports,[])
        render.assert_not_called()

    def test_selected_mono_vocal_is_processed_once_and_drums_unmodified(self):
        vocal=next(row for row in self.hints if row['group']=='vocals')
        selection={vocal['file']:{'enabled':True,'style':'tape',
                                   'drive':.5,'mix':.1}}
        before=Path(vocal['file']).read_bytes()
        prepared,report=prepare_selected_stems(
            self.config,selection,Path(self.temp.name)/'cache')
        self.assertEqual(len(prepared),1)
        self.assertEqual(len(report),1)
        self.assertEqual(report[0]['source'],vocal['file'])
        with sf.SoundFile(prepared[str(next(i for i,r in enumerate(self.config['tracks'])
                                            if r['file']==vocal['file']))]) as processed:
            self.assertEqual(processed.channels,1)
            self.assertEqual(processed.frames,48000)
        self.assertEqual(Path(vocal['file']).read_bytes(),before)
        self.assertFalse(any('drums' in r['source'] for r in report))
        prepared2,report2=prepare_selected_stems(
            self.config,selection,Path(self.temp.name)/'cache')
        self.assertEqual(prepared,prepared2)

    def test_unknown_source_or_excessive_settings_rejected(self):
        key=self.hints[0]['file']
        for chosen in (
            {'/elsewhere/missing.wav':{'enabled':True,'style':'tape','drive':.5,'mix':.1}},
            {key:{'enabled':True,'style':'tape','drive':15,'mix':.1}},
            {key:{'enabled':True,'style':'clip','drive':1,'mix':.1}},
        ):
            with self.assertRaises(ValueError):
                validated_selections(self.config,chosen)

    def test_settings_change_invalidates_old_master_reuse(self):
        master=Path(self.temp.name)/'master.wav'
        wav(master)
        mixes={}
        for name in ('balanced','vocal-focus','punchy'):
            p=Path(self.temp.name)/(name+'.wav')
            wav(p)
            mixes[name]=str(p)
        result={'status':'qc_pass','file':str(master),
                'album_source_signature':source_signature(self.folder,'stems'),
                'album_pipeline':PIPELINE_ID,'album_candidates':mixes}
        row={'status':'qc_pass','kind':'stems','path':str(self.folder),
             'result':result,'stem_saturation':{}}
        self.assertTrue(can_reuse_master(row))
        vocal=next(item for item in self.hints if item['group']=='vocals')
        row['stem_saturation']={vocal['file']:{'enabled':True,'style':'tape',
                                               'drive':.5,'mix':.1}}
        self.assertFalse(can_reuse_master(row))
        self.assertNotEqual(selection_signature({}),selection_signature(row['stem_saturation']))

    def test_pipeline_ui_syntax_and_branded_title(self):
        for filename in ('album_studio_ui.py','album_stem_pipeline.py',
                         'stem_saturation.py','album_saturation_preview.py','version.py'):
            ast.parse((ROOT/filename).read_text(encoding='utf-8'))
        ui=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        pipeline=(ROOT/'album_stem_pipeline.py').read_text(encoding='utf-8')
        self.assertIn("fx_btn=QPushButton('⚡ FX Stems')",ui)
        self.assertIn('class StemSaturationDialog(QDialog):',ui)
        self.assertIn("track['stem_saturation']=dialog.selection",ui)
        self.assertIn("track['status']='waiting'",ui)
        self.assertIn('prepare_selected_stems(',pipeline)
        self.assertIn('prepared=prepared',pipeline)
        self.assertIn('stem_saturation=row.get(\'stem_saturation\')',ui)
        title=(ROOT/'version.py').read_text(encoding='utf-8')
        self.assertIn('FRANKENSTEM',title)


if __name__=='__main__':
    unittest.main()
