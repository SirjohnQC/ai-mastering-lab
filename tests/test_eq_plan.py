import importlib.util
from pathlib import Path
import json
import unittest

SPEC = importlib.util.spec_from_file_location('eq_plan', Path(__file__).resolve().parents[1] / 'src/mastering_lab/eq_plan.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

EVAL = {'status':'ok','metrics':{'balanced':{'spectral_shares':{
    'sub_bass_20_120':0.141,'low_mid_120_500':0.365,
    'mid_500_5000':0.449,'high_5000_20000':0.044}}}}

class EQPlanTests(unittest.TestCase):
    def test_valid_proposal(self):
        result = module.validate_plan({'moves':[{'target':'balanced_premix',
            'evidence_band':'low_mid_120_500', 'frequency_hz':280,
            'gain_db':-0.7,'reason':'Essai de réduire les bas médiums'}]}, EVAL)
        self.assertEqual(result['moves'][0]['spectral_share_pct'], 36.5)
    def test_empty_is_ok(self):
        self.assertEqual(module.validate_plan({'moves':[]},EVAL)['moves'],[])
    def test_gain_rejected(self):
        with self.assertRaises(ValueError):
            module.validate_plan({'moves':[{'target':'balanced_premix','evidence_band':'low_mid_120_500',
            'frequency_hz':280,'gain_db':3.0,'reason':'Essai de réduire les bas médiums'}]},EVAL)
    def test_wrong_band_rejected(self):
        with self.assertRaises(ValueError):
            module.validate_plan({'moves':[{'target':'balanced_premix','evidence_band':'low_mid_120_500',
            'frequency_hz':8000,'gain_db':-1,'reason':'Essai de réduire les bas médiums'}]},EVAL)
    def test_stem_target_rejected(self):
        with self.assertRaises(ValueError):
            module.validate_plan({'moves':[{'target':'lead_vocals','evidence_band':'low_mid_120_500',
            'frequency_hz':280,'gain_db':-1,'reason':'Essai de réduire les bas médiums'}]},EVAL)
    def test_non_finite_rejected(self):
        with self.assertRaises(ValueError):
            module.validate_plan({'moves':[{'target':'balanced_premix','evidence_band':'low_mid_120_500',
            'frequency_hz':280,'gain_db':float('nan'),'reason':'Essai de réduire les bas médiums'}]},EVAL)
    def test_ollama_payload_and_output(self):
        def transport(payload):
            self.assertFalse(payload['think'])
            self.assertEqual(payload['model'],'hermes3:8b')
            return {'done_reason':'stop','message':{'content':json.dumps({'moves':[]})}}
        result = module.propose_eq_plan(EVAL,requester=transport)
        self.assertEqual(result['moves'],[])
    def test_length_failure(self):
        with self.assertRaisesRegex(ValueError,'limite de tokens'):
            module.propose_eq_plan(EVAL,requester=lambda _: {'done_reason':'length','message':{'content':''}})

if __name__=='__main__':
    unittest.main()
