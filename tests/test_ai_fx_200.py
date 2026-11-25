import json
import tempfile
import unittest
from pathlib import Path
from mastering_lab.eq_feedback import record_eq_choice, summarize_eq_preferences
from mastering_lab.ai_fx_intelligence import request_eq_proposal

FEATURES={'spectral_shares':[.125]*8}
MOVE={'band_index':3, 'frequency_hz':350., 'gain_db':-.5, 'reason':'Essai subtil pour écoute comparative'}

class TestEQMemory(unittest.TestCase):
    def test_empty_missing_or_invalid_memory(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'eq.json'
            self.assertIsNone(summarize_eq_preferences(path))
            path.write_text('{broken',encoding='utf-8')
            self.assertIsNone(summarize_eq_preferences(path))

    def test_confirmed_decision_no_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            a,b=root/'before.wav',root/'after.wav'
            a.write_bytes(b'a');b.write_bytes(b'b')
            history=root/'prefs.json'
            record_eq_choice(history,before=a,after=b,choice='before',moves=[{'requested':MOVE}],song='Song')
            memory=summarize_eq_preferences(history)
            self.assertEqual(memory['rejected_before'],1)
            self.assertEqual(memory['accepted_after'],0)
            self.assertEqual(memory['recent_examples'][0]['tested_moves'][0]['gain_db'],-.5)
            self.assertNotIn(str(root),json.dumps(memory))
            self.assertNotIn('Song',json.dumps(memory))

    def test_reject_unknown_gains_and_unconfirmed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'prefs.json'
            path.write_text(json.dumps([
                {'preferred':'after','moves':[{'requested':{**MOVE,'gain_db':500}}]},
                {'preferred':'pending','moves':[{'requested':MOVE}]},
                {'preferred':'after','moves':[{'requested':MOVE}]},
            ]),encoding='utf-8')
            self.assertEqual(summarize_eq_preferences(path)['total_confirmed'],1)

    def test_prompt_contains_confirmed_preferences(self):
        calls=[]
        memory={'total_confirmed':1,'recent_examples':[{'preferred':'before','tested_moves':[{'band_index':3,'frequency_hz':350,'gain_db':-.5}]}]}
        def responder(payload):
            calls.append(payload)
            return {'message':{'content':json.dumps({'summary':'Aucune variation nécessaire','moves':[]})}}
        result=request_eq_proposal(FEATURES,eq_preferences=memory,requester=responder)
        self.assertEqual(result['moves'],[])
        self.assertEqual(json.loads(calls[0]['messages'][1]['content'])['confirmed_eq_preferences'],memory)
        self.assertIn('do not infer',calls[0]['messages'][0]['content'])

    def test_ui_wiring(self):
        ui=(Path(__file__).parents[1]/'src'/'mastering_lab'/'auto_studio_ui.py').read_text()
        self.assertIn('eq_preferences_path=self.root',ui)
        self.assertIn('fx_memory_status',ui)
        self.assertIn('record_eq_choice(',ui)

if __name__=='__main__':unittest.main()
