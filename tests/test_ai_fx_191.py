import json
import tempfile
import unittest
from pathlib import Path
from mastering_lab.ai_fx_intelligence import request_eq_proposal
from mastering_lab.eq_feedback import record_eq_choice

FEATURES = {'spectral_shares':[.125]*8}

class AuditionTests(unittest.TestCase):
    def test_default_allows_no_moves(self):
        calls=[]
        def fn(body):
            calls.append(body)
            return {'message':{'content':json.dumps({'summary':'Pas assez de preuves','moves':[]})}}
        plan=request_eq_proposal(FEATURES,requester=fn)
        self.assertEqual(plan['moves'],[])
        self.assertIn('Prefer zero moves', calls[0]['messages'][0]['content'])

    def test_creative_optional_prompt_not_claiming_defects(self):
        calls=[]
        def fn(body):
            calls.append(body)
            return {'message':{'content':json.dumps({'summary':'Essai facultatif','moves':[{'band_index':3,'frequency_hz':350,'gain_db':-.4,'reason':'Comparer la chaleur du mix.'}]})}}
        plan=request_eq_proposal(FEATURES,requester=fn,creative=True)
        self.assertEqual(plan['moves'][0]['gain_db'],-.4)
        self.assertIn('CREATIVE experiment',calls[0]['messages'][0]['content'])
        self.assertIn('cannot hear',calls[0]['messages'][0]['content'])

    def test_eq_feedback_requires_choice_and_both_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            before,after=root/'a.wav',root/'b.wav'
            before.write_bytes(b'x');after.write_bytes(b'y')
            path=root/'settings'/'eq_preferences.json'
            with self.assertRaises(ValueError):
                record_eq_choice(path,before=before,after=after,choice='maybe',moves=[])
            self.assertFalse(path.exists())
            self.assertEqual(record_eq_choice(path,before=before,after=after,choice='after',moves=[{'gain_db':-.5}],song='Test'),1)
            item=json.loads(path.read_text(encoding='utf8'))[0]
            self.assertEqual(item['preferred'],'after')
            self.assertEqual(item['song'],'Test')
            self.assertEqual(len(item['moves']),1)

    def test_ui_wires_explicit_confirmation(self):
        text=(Path(__file__).parents[1]/'src'/'mastering_lab'/'auto_studio_ui.py').read_text()
        self.assertIn('Je préfère Avant',text)
        self.assertIn('Je préfère Après',text)
        self.assertIn('record_eq_choice(',text)
        self.assertIn("_fx_ab_player.load(source, self._fx_audition)",text)
        self.assertIn('self._fx_ab_player.stop()',text)

if __name__=='__main__': unittest.main()
