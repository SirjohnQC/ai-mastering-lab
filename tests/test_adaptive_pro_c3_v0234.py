"""v0.23.4 regression tests for song-aware discrete Pro-C 3 settings."""
import ast
import tempfile
from pathlib import Path
import unittest

import numpy as np
import soundfile as sf

from mastering_lab.adaptive_pro_c3 import source_dynamics, plan_scenarios, prepare_adaptive
from mastering_lab.pro_c3_parameter_validation import prepare_discrete_scenario

ROOT = Path(__file__).resolve().parents[1]


def fake_grid():
    texts = {
        'threshold':{.70:'-18 dB',.85:'-9 dB'},
        'ratio':{.30:'1.5:1',.70:'6:1'},
        'attack':{.30:'6.755 ms'},
        'release':{.30:'115 ms'},
    }
    return {'read_only':True,'method':'getText',
            'display_mapping_status':{k:'text_grid_plausible' for k in texts},
            'probe_points':{k:[{'normalized':n,'physical':float(t.split()[0].split(':')[0]),
                                'display_text':t} for n,t in entries.items()]
                            for k,entries in texts.items()}}


class SongAwareTests(unittest.TestCase):
    def test_exact_known_grid_points(self):
        for data in ({'peak_dbfs':-11,'crest_db':15},
                     {'peak_dbfs':-2,'crest_db':7},
                     {'peak_dbfs':-5,'crest_db':11}):
            plan = plan_scenarios(data)
            self.assertEqual(set(plan['scenarios']),{'gentle','firm'})
            for values in plan['scenarios'].values():
                expected,changes=prepare_discrete_scenario(fake_grid(),values)
                self.assertEqual(len(expected),4)
                self.assertIn((19,0.0),changes)
        self.assertEqual(plan_scenarios({'peak_dbfs':-11,'crest_db':15})
                         ['scenarios']['gentle']['threshold'],.70)
        self.assertEqual(plan_scenarios({'peak_dbfs':-2,'crest_db':7})
                         ['scenarios']['firm']['threshold'],.85)

    def test_unverified_values_rejected(self):
        valid={'threshold':.70,'ratio':.30,'attack':.30,'release':.30}
        for key in valid:
            bad=dict(valid);bad[key]=.333
            with self.assertRaises(ValueError):
                prepare_discrete_scenario(fake_grid(),bad)

    def test_adaptive_planner_uses_real_song_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.wav'
            t=np.arange(48000,dtype='float64')/48000
            tone=np.sin(2*np.pi*220*t).astype('float32')*.18
            samples=np.column_stack([tone,tone]).astype('float32')
            sf.write(str(path),samples,48000,subtype='FLOAT')
            measured=source_dynamics(path)
            self.assertLess(measured['peak_dbfs'],-10)
            plan,prepared=prepare_adaptive(fake_grid(),path)
            self.assertEqual(plan['version'],1)
            self.assertEqual(set(prepared),{'gentle','firm'})
            self.assertEqual(prepared['gentle'][1][-1],(19,0.0))

    def test_render_cache_bumped_and_song_aware_opt_in(self):
        ui=(ROOT/'src/mastering_lab/unified_comparison.py').read_text(encoding='utf-8')
        audio=(ROOT/'src/mastering_lab/pro_c3_song_preview.py').read_text(encoding='utf-8')
        ast.parse(ui)
        ast.parse(audio)
        self.assertIn('CACHE_RENDER_VERSION = 2',ui)
        self.assertIn('song_aware=True',ui)
        self.assertIn('validate_readback(result, expected)',audio)
        self.assertIn('verify_output(output, info, tail)',audio)
        self.assertIn('adaptive_plan',audio)

if __name__=='__main__':
    unittest.main()
