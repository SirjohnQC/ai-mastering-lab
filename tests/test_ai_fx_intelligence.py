import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mastering_lab.ai_fx_intelligence import (validate_eq_proposal, request_eq_proposal,
    propose_for_wav, render_approved_eq)

FEATURES={'spectral_shares':[.1]*8}
GOOD={'summary':'Essai facultatif et conservateur.',
      'moves':[{'band_index':3,'frequency_hz':330,'gain_db':-.5,
                'reason':'Essai léger pour comparer à l’oreille.'}]}

class FXTests(unittest.TestCase):
    def test_empty_plan_valid(self):
        self.assertEqual(validate_eq_proposal({'summary':'Pas assez de preuves','moves':[]}, FEATURES)['moves'],[])

    def test_valid(self):
        self.assertEqual(validate_eq_proposal(GOOD, FEATURES)['moves'][0]['gain_db'],-.5)

    def test_reject_bad_parameters(self):
        cases=[
            dict(GOOD, moves=[dict(GOOD['moves'][0], gain_db=3)]),
            dict(GOOD, moves=[dict(GOOD['moves'][0], frequency_hz=3000)]),
            dict(GOOD, moves=[dict(GOOD['moves'][0], gain_db=float('nan'))]),
            dict(GOOD, moves=[dict(GOOD['moves'][0], band_index=True)]),
            dict(GOOD, moves=GOOD['moves']*3),
            dict(GOOD, danger=True),
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError): validate_eq_proposal(case,FEATURES)

    def test_request_uses_only_measured_features_and_references(self):
        received={}
        def responder(body):
            received.update(body)
            return {'message':{'content':json.dumps(GOOD)}}
        result=request_eq_proposal(FEATURES, {'count':2}, requester=responder)
        self.assertEqual(result['moves'][0]['frequency_hz'],330)
        self.assertEqual(received['model'],'hermes3:8b')
        user=json.loads(received['messages'][1]['content'])
        self.assertEqual(user['reference_context']['count'],2)

    def test_real_wav_proposal_source_signature(self):
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'song.wav'
            t=np.arange(44100)/44100
            sf.write(src, np.column_stack([.1*np.sin(t*440*2*np.pi)]*2),44100)
            result=propose_for_wav(src, requester=lambda _: {'message':{'content':json.dumps(GOOD)}})
            self.assertEqual(result['source'],str(src.resolve()))
            self.assertEqual(result['source_signature'][1],src.stat().st_size)

    def test_render_rejects_changed_source_before_host(self):
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'song.wav'; sf.write(src,np.zeros((9000,2)),44100)
            src_stat=src.stat()
            plan={'source':str(src.resolve()),'source_signature':[str(src.resolve()),0,0],
                  'source_features':FEATURES, **GOOD}
            with self.assertRaisesRegex(ValueError,'Source modifiée'):
                render_approved_eq(src,plan,root=d)

    def test_render_end_to_end_fake_vst(self):
        import numpy as np
        import soundfile as sf
        from mastering_lab.ai_fx_intelligence import _signature
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'song.wav'; sf.write(src,np.zeros((9000,2)),44100)
            host=root/'mastering-host.exe';host.touch()
            plugin=root/'FabFilter Pro-Q 4.vst3'; plugin.mkdir()
            plan={'source':str(src.resolve()),'source_signature':_signature(src),
                  'source_features':FEATURES, **GOOD}
            def runner(hostpath, command, **kwargs):
                if command=='inspect':
                    params=[{'index':i,'name':'Unused','automatable':True} for i in range(4)]
                    for i,name in ((0,'Band 1 Enable'),(2,'Band 1 Frequency'),(3,'Band 1 Gain')): params[i]['name']=name
                    return {'name':'FabFilter Pro-Q 4','parameters':params}
                changes=dict(kwargs['parameter_changes'])
                if 'probe' not in str(kwargs['input_file']):
                    import shutil
                    shutil.copyfile(kwargs['input_file'], kwargs['output_file'])
                frequency=changes[2]*1000
                gain=(changes[3]-.5)*60
                return {'parameter_changes':[{'index':0,'text':'On'},
                    {'index':2,'text':f'{frequency:.2f} Hz'},
                    {'index':3,'text':f'{gain:.2f} dB'}], 'tail_samples':0}
            result=render_approved_eq(src,plan,root=root,host=host,plugin=plugin,runner=runner)
            self.assertTrue(Path(result['after']).exists())
            self.assertEqual(Path(result['original']).read_bytes(),Path(result['after']).read_bytes())
            self.assertNotEqual(result['after'],str(src))
            result2=render_approved_eq(src,plan,root=root,host=host,plugin=plugin,runner=runner)
            self.assertNotEqual(result['after'],result2['after'])

if __name__=='__main__': unittest.main()
