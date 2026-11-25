import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import soundfile as sf
from mastering_lab.eq_audition import _db_text, _hz_text, _verify_layout, render_eq_audition
import sys
import types

class EQAuditionTests(unittest.TestCase):
    def test_text(self):
        self.assertEqual(_hz_text('0.300 kHz'), 300)
        self.assertEqual(_hz_text('300 Hz'), 300)
        self.assertEqual(_db_text('-0.50 dB'), -0.5)
        with self.assertRaises(ValueError): _hz_text('what')

    def test_reject_wrong_plugin(self):
        with self.assertRaises(ValueError):
            _verify_layout({'name':'Fake EQ','parameters':[]})

    def test_render_and_never_touch_original(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            host=root/'native/build/mastering-host_artefacts/Release/mastering-host.exe'
            host.parent.mkdir(parents=True)
            host.touch()
            plugin=root/'FabFilter Pro-Q 4.vst3'
            plugin.mkdir()
            before=root/'balanced.wav'
            samples=np.zeros((4800,2),dtype='float32')
            samples[100:200]=0.125
            sf.write(str(before), samples, 48000, subtype='PCM_24')
            after_dummy=root/'vocal.wav'; sf.write(str(after_dummy),samples,48000,subtype='PCM_24')
            third=root/'punchy.wav'; sf.write(str(third),samples,48000,subtype='PCM_24')
            comparison={'status':'ok','variants':{'balanced':{'wav':str(before)},'vocal-focus':{'wav':str(after_dummy)},'punchy':{'wav':str(third)}}}
            plan={'moves':[{'target':'balanced_premix','evidence_band':'low_mid_120_500', 'frequency_hz':300,'gain_db':-0.5,'reason':'Essai prudent à valider à l’écoute'}]}
            def fake_runner(_host, command, **kwargs):
                if command=='inspect':
                    parameters=[{'index':i,'automatable':True,'name':name} for i,name in enumerate(['Band 1 Enabled','Band 1 Shape','Band 1 Frequency','Band 1 Gain'])]
                    return {'name':'FabFilter Pro-Q 4','parameters':parameters}
                assert command=='render'
                changes=dict(kwargs['parameter_changes'])
                f=10*(30000/10)**changes[2]
                gain=(changes[3]-.5)*60
                input_path=Path(kwargs['input_file'])
                wav,sr=sf.read(input_path, dtype='float32')
                sf.write(str(kwargs['output_file']),wav,sr, subtype='PCM_24')
                return {'status':'ok','tail_samples':0,'parameter_changes':[
                    {'index':0,'text':'On'},
                    {'index':2,'text':f'{f:.3f} Hz'},
                    {'index':3,'text':f'{gain:.2f} dB'}]}
            with patch.dict(sys.modules, {'mastering_lab.mix_evaluator':types.SimpleNamespace(evaluate_comparison=lambda comparison: {'status':'ok','metrics':{'balanced':{'spectral_shares':{'sub_bass_20_120':.1,'low_mid_120_500':.37,'mid_500_5000':.45,'high_5000_20000':.08}}}})}):
                result=render_eq_audition(comparison,plan,root=root,plugin=plugin,host=host,runner=fake_runner)
            self.assertTrue(Path(result['after']).is_file())
            self.assertTrue(Path(result['report']).is_file())
            self.assertEqual(sf.info(result['after']).frames,4800)
            self.assertEqual(sf.info(str(before)).frames,4800)
            self.assertNotEqual(result['after'],str(before))

if __name__=='__main__': unittest.main()
