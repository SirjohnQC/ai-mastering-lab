"""v0.23.3 measured-advisor unit tests (no Qt or JUCE required)."""
import ast
from pathlib import Path
import unittest

from mastering_lab.compression_advisor import suggest_compression

ROOT = Path(__file__).resolve().parents[1]


def metrics():
    result = {}
    for mix in ('balanced','vocal-focus','punchy'):
        result[mix+'/original'] = dict(rms_dbfs=-17, sample_peak_dbfs=-2,
                                        crest_db=15)
        result[mix+'/gentle'] = dict(rms_dbfs=-17.25, sample_peak_dbfs=-2.4,
                                      crest_db=14, rms_delta_db=-.25,
                                      max_absolute_sample_difference=.14,
                                      same_samples_as_original=False)
        result[mix+'/firm'] = dict(rms_dbfs=-19, sample_peak_dbfs=-4.5,
                                    crest_db=11.8, rms_delta_db=-2,
                                    max_absolute_sample_difference=.4,
                                    same_samples_as_original=False)
    return result


class AdaptiveAdvisorTests(unittest.TestCase):
    def test_intensity_suggestion_changes_without_plugin_writes(self):
        data = metrics()
        gentle = suggest_compression(data, 'balanced', 'natural')
        firm = suggest_compression(data, 'balanced', 'punchy')
        self.assertIn(gentle['variant'], ('original','gentle'))
        self.assertEqual(firm['variant'], 'firm')

    def test_identical_gentle_is_rejected(self):
        data = metrics()
        data['balanced/gentle']['same_samples_as_original'] = True
        item = suggest_compression(data, 'balanced', 'natural')
        self.assertFalse(item['candidates']['gentle']['eligible'])

    def test_clipping_and_missing_measurements_fallback(self):
        data = metrics()
        data['balanced/gentle']['sample_peak_dbfs'] = -.01
        data['balanced/firm']['sample_peak_dbfs'] = -.01
        item = suggest_compression(data, 'balanced', 'punchy')
        self.assertEqual(item['variant'], 'original')
        self.assertEqual(suggest_compression({}, 'balanced')['variant'], 'original')

    def test_ui_never_grants_automatic_mastering_approval(self):
        ui=(ROOT/'src/mastering_lab/unified_comparison.py').read_text(encoding='utf-8')
        ast.parse(ui)
        funcs={n.name:ast.get_source_segment(ui,n) for n in ast.walk(ast.parse(ui))
               if isinstance(n,ast.FunctionDef)}
        self.assertIn('self.select_compression',funcs['preview_suggestion'])
        self.assertNotIn('self.approve(',funcs['preview_suggestion'])
        self.assertNotIn('self._approved =',funcs['preview_suggestion'])
        self.assertIn('self._approved', funcs['master_source'])
        self.assertIn('self._update_advisor()', funcs['_update_active_diagnostics'])

if __name__ == '__main__':
    unittest.main()
