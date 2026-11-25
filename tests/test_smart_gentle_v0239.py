"""v0.23.9 Smart Gentle safe candidate trials (no Windows VST required)."""
from __future__ import annotations
import ast
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from mastering_lab.smart_gentle import gentle_candidates, evaluate_gentle, choose_gentle

ROOT = Path(__file__).resolve().parents[1]
RATE = 48000


class SmartGentleTests(unittest.TestCase):
    def test_only_two_exact_known_threshold_points(self):
        base = {'threshold':.85, 'ratio':.30, 'attack':.30, 'release':.30}
        trials = gentle_candidates(base)
        self.assertEqual([item['threshold'] for _,item in trials],[.85,.70])
        self.assertTrue(all(item['ratio']==.30 for _,item in trials))
        for key in base:
            broken=dict(base); broken[key]=.37
            with self.assertRaises(ValueError):
                gentle_candidates(broken)

    def test_choose_optimal_safe_candidate_from_actual_pcm(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            seconds=4
            time=np.arange(seconds*RATE,dtype='float64')/RATE
            loud=((time.astype(int)%2)==0)
            original=np.sin(2*np.pi*220*time)*np.where(loud,.75,.10)
            gentle=np.sin(2*np.pi*220*time)*np.where(loud,.70,.10)
            firm=np.sin(2*np.pi*220*time)*np.where(loud,.25,.10)
            paths={}
            for name,data in [('original',original),('gentle',gentle),('firm',firm)]:
                path=root/(name+'.wav')
                sf.write(str(path),np.column_stack([data,data]).astype('float32'),
                         RATE,subtype='FLOAT')
                paths[name]=path
            frames=seconds*RATE
            good=evaluate_gentle(paths['original'],paths['gentle'],frames=frames)
            heavy=evaluate_gentle(paths['original'],paths['firm'],frames=frames)
            original_copy=evaluate_gentle(paths['original'],paths['original'],frames=frames)
            self.assertEqual(good['status'],'eligible')
            self.assertEqual(original_copy['status'],'rejected')
            self.assertEqual(heavy['status'],'rejected')
            result=choose_gentle([
                {'name':'gentle-1','path':str(paths['gentle']),
                 'threshold':.85,'metrics':good},
                {'name':'gentle-2','path':str(paths['firm']),
                 'threshold':.70,'metrics':heavy}])
            self.assertEqual(result['selected'],'gentle-1')

    def test_nothing_suitable_uses_explicit_original_fallback(self):
        trials=[{'name':'gentle-1','path':'fake.wav','threshold':.85,
                 'metrics':{'status':'rejected','reason':'No effect'}}]
        result=choose_gentle(trials)
        self.assertEqual(result['status'],'fallback_original')
        self.assertEqual(result['selected'],'original')

    def test_ui_approval_gate_and_audio_cache_version(self):
        ui=(ROOT/'src/mastering_lab/unified_comparison.py').read_text(encoding='utf-8')
        preview=(ROOT/'src/mastering_lab/pro_c3_song_preview.py').read_text(encoding='utf-8')
        for source in [ui,preview]:
            ast.parse(source)
        self.assertIn('CACHE_RENDER_VERSION = 3',ui)
        self.assertIn('smart_gentle=True',ui)
        self.assertIn('self._gentle_is_fallback',ui)
        self.assertIn("selected == 'gentle' and report.get('smart_gentle'",preview)
        self.assertIn('validate_readback(rendered, expected)',preview)
        self.assertIn('verify_output(trial_output, info, tail)',preview)
        self.assertIn("gentle_output = session / 'gentle.wav'",preview)
        self.assertIn('smart_gentle_preview',preview)


if __name__ == '__main__':
    unittest.main()
