import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mastering_lab.preference_learning import (save_choice, load_preferences, preference_context, clear_preferences)
from mastering_lab.album_mix_evaluation import choose_candidate

M = {key: {'rms_dbfs': -18.0, 'sample_peak_dbfs': -3., 'crest_db': 15.,
           'stereo_correlation': .9, 'sample_peak_clipped': False,
           'sample_rate': 48000, 'duration_seconds': 60.}
     for key in ('balanced', 'vocal-focus', 'punchy')}

class PreferenceTests(unittest.TestCase):
    def test_explicit_feedback_and_context(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'settings' / 'mix_preferences.json'
            self.assertIsNone(preference_context(path))
            self.assertEqual(save_choice(path, selected='vocal-focus', metrics=M, ai_suggested='balanced',song='Test'), 1)
            self.assertEqual(preference_context(path)['variant_counts']['vocal-focus'], 1)
            self.assertEqual(load_preferences(path)['examples'][0]['ai_suggested'], 'balanced')
            clear_preferences(path)
            self.assertEqual(load_preferences(path)['examples'], [])

    def test_reject_bad_metrics_and_variant(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'file.json'
            with self.assertRaises(ValueError):
                save_choice(path, selected='bad', metrics=M)
            bad = {**M, 'balanced': {'rms_dbfs': float('nan')}}
            with self.assertRaises(ValueError):
                save_choice(path, selected='balanced', metrics=bad)
            self.assertFalse(path.exists())

    def test_bounded_history(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'history.json'
            for _ in range(202):
                save_choice(path, selected='punchy', metrics=M)
            self.assertEqual(len(load_preferences(path)['examples']), 200)
            self.assertEqual(preference_context(path)['count'], 40)

    def test_selection_with_preference_context_no_safety_bypass(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'history.json'
            save_choice(path, selected='vocal-focus', metrics=M)
            with patch('mastering_lab.album_mix_evaluation.measure_candidates', return_value=M), \
                 patch('mastering_lab.album_mix_evaluation.request_selection', return_value={'selected':'punchy', 'reason':'RMS et crest valides'}) as ask:
                selected, decision = choose_candidate({'balanced':'a', 'vocal-focus':'b', 'punchy':'c'}, preferences_path=path)
                self.assertEqual(selected, 'punchy')
                self.assertTrue(decision['preferences_used'])
                self.assertEqual(ask.call_args.kwargs['preferences']['variant_counts']['vocal-focus'], 1)
            unsafe={key: dict(value) for key,value in M.items()}
            unsafe['punchy']['sample_peak_clipped']=True
            with patch('mastering_lab.album_mix_evaluation.measure_candidates', return_value=unsafe), \
                 patch('mastering_lab.album_mix_evaluation.request_selection', return_value={'selected':'punchy', 'reason':'Preference'}) as ask:
                selected, decision = choose_candidate({'balanced':'a', 'vocal-focus':'b', 'punchy':'c'}, preferences_path=path)
                self.assertEqual((selected,decision['mode']), ('balanced','fallback'))

    def test_ui_wiring(self):
        ui=(Path(__file__).resolve().parents[1]/'src/mastering_lab/auto_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('Mémoriser mon choix', ui)
        self.assertIn('def _save_preference', ui)
        self.assertIn('def _clear_preferences_clicked', ui)
        self.assertIn('preferences_path=preference_path(self.root)', ui)
        self.assertIn('self.pref_save.setEnabled(False)', ui)

if __name__ == '__main__': unittest.main()
