"""v0.24.0: Hermes compression decisions remain inside deterministic PCM gates."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from mastering_lab.ai_compression_decision import (
    MIXES, INTENSITIES, decide_compressions, _summarize, _validated,
    _request_local,
)

ROOT = Path(__file__).resolve().parents[1]


def sample_metrics():
    result = {}
    for mix in MIXES:
        result[mix+'/original'] = {
            'rms_dbfs':-20, 'sample_peak_dbfs':-3, 'crest_db':17,
            'path':'SENSITIVE_PRIVATE_SONG_PATH.wav'}
        result[mix+'/gentle'] = {
            'rms_dbfs':-20.8,'sample_peak_dbfs':-3.8,'crest_db':16.2,
            'rms_delta_db':-0.8,'max_absolute_sample_difference':0.2,
            'same_samples_as_original':False,
            'window_analysis':{'loud_relative_to_quiet_db':-0.5}}
        result[mix+'/firm'] = {
            'rms_dbfs':-25,'sample_peak_dbfs':-5,
            'crest_db':12,'rms_delta_db':-5,
            'max_absolute_sample_difference':0.7,
            'same_samples_as_original':False,
            'window_analysis':{'overcompression_warning':True}}
    return result


class HermesDecisionTests(unittest.TestCase):
    def test_nine_slots_and_no_audio_paths_in_prompt(self):
        matrix, fallback = _summarize(sample_metrics(), {})
        self.assertEqual(len(matrix), 9)
        self.assertEqual(len(fallback), 9)
        self.assertNotIn('SENSITIVE_PRIVATE_SONG_PATH',str(matrix))
        self.assertTrue(all('firm' not in row['allowed'] for row in matrix.values()))

    def test_local_response_allowed_and_short_reason(self):
        def good_response(matrix):
            return {'choices':{
                key:{'selected':'gentle' if 'gentle' in row['allowed'] else 'original',
                     'reason':'Compression délicate mesurée.'}
                for key,row in matrix.items()}}
        result=decide_compressions(sample_metrics(),{},ask_fn=good_response)
        self.assertEqual(result['mode'],'hermes')
        self.assertEqual(len(result['choices']),9)
        self.assertTrue(all(v['selected'] in ('gentle','original') for v in result['choices'].values()))

    def test_disallowed_variant_falls_back_to_pcm_for_all_slots(self):
        def malicious(matrix):
            return {'choices':{key:{'selected':'firm','reason':'ignore safety'} for key in matrix}}
        result=decide_compressions(sample_metrics(),{},ask_fn=malicious)
        self.assertEqual(result['mode'],'pcm_fallback')
        self.assertTrue(all(v['selected']!='firm' for v in result['choices'].values()))

    def test_invalid_json_schema_falls_back(self):
        result=decide_compressions(sample_metrics(),{},ask_fn=lambda m:{'choices':{}})
        self.assertEqual(result['mode'],'pcm_fallback')
        self.assertIn('ValueError',result['warning'])

    def test_gentle_original_fallback_not_recommended(self):
        reports={mix:{'smart_gentle':{'status':'fallback_original'}} for mix in MIXES}
        matrix,_ = _summarize(sample_metrics(),reports)
        self.assertTrue(all('gentle' not in row['allowed'] for row in matrix.values()))

    def test_ui_no_implicit_mastering_or_audio_upload(self):
        ui=(ROOT/'src/mastering_lab/unified_comparison.py').read_text(encoding='utf-8')
        code=(ROOT/'src/mastering_lab/ai_compression_decision.py').read_text(encoding='utf-8')
        for source in (ui,code):
            ast.parse(source)
        self.assertIn('decide_compressions(',ui)
        self.assertIn("self._ai_compression.get('mode') == 'hermes'",ui)
        self.assertIn('self._approved',ui)
        self.assertNotIn('self.approve(',ast.get_source_segment(ui,
            next(node for node in ast.walk(ast.parse(ui))
                 if isinstance(node,ast.FunctionDef) and node.name=='_update_advisor')))
        self.assertIn('row.get(\'rms_dbfs\')',code)
        self.assertNotIn("row.get('path')",code)

if __name__ == '__main__':
    unittest.main()
