"""v0.23.7: Gentle evidence explanations without definitive compression claims."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from mastering_lab.compression_explainer import explain_gentle

ROOT = Path(__file__).resolve().parents[1]


def evidence(*, peak=-3.0, crest=18.5, delta=0.02, quiet=True, identical=False):
    metrics = {
        'balanced/original': {'rms_dbfs': -21.5, 'sample_peak_dbfs':peak, 'crest_db':crest},
        'balanced/gentle': {'rms_delta_db':delta,
                            'same_samples_as_original':identical,
                            'window_analysis': {
                                'status':'measured',
                                'effect_nearly_inaudible_warning':quiet,
                                'loud_relative_to_quiet_db':-0.04}},
    }
    report = {
        'scenarios': {'gentle':{'parameters': {
            'threshold':{'actual_physical':-9.0,'plugin_text':'-9 dB'}}}}}
    return metrics, report


class GentleExplanationTests(unittest.TestCase):
    def test_loud_dynamic_mix_is_not_assumed_to_be_compressed(self):
        metrics,report = evidence()
        item=explain_gentle(metrics, 'balanced', report)
        self.assertEqual(item['status'], 'subtle_unresolved')
        self.assertNotIn('déjà compressé',item['reason'])

    def test_peak_under_actual_threshold(self):
        metrics, report = evidence(peak=-14.0)
        item=explain_gentle(metrics,'balanced',report)
        self.assertEqual(item['status'], 'probably_below_threshold')
        self.assertEqual(item['evidence']['threshold_readback_db'],-9)

    def test_identical_audio_is_not_treated_as_successful_compression(self):
        metrics,report=evidence(identical=True)
        self.assertEqual(explain_gentle(metrics,'balanced',report)['status'],'identical')

    def test_dense_does_not_claim_already_compressed(self):
        metrics,report=evidence(crest=7)
        item=explain_gentle(metrics,'balanced',report)
        self.assertEqual(item['status'],'dense_input_possible')
        self.assertIn('ne prouve PAS',item['reason'])

    def test_measured_change(self):
        metrics,report=evidence(delta=-0.85,quiet=False)
        self.assertEqual(explain_gentle(metrics,'balanced',report)['status'],'measurable')

    def test_missing_source_is_unavailable(self):
        self.assertEqual(explain_gentle({},'balanced')['status'],'unavailable')

    def test_ui_uses_local_diagnostics_and_no_implicit_approval(self):
        ui=(ROOT/'src/mastering_lab/unified_comparison.py').read_text(encoding='utf-8')
        ast.parse(ui)
        self.assertIn('explain_gentle(',ui)
        self.assertIn('self.gentle_explanation.setText(',ui)
        self.assertIn("ver = QLabel('v0.23.7')",ui)
        source=(ROOT/'src/mastering_lab/compression_explainer.py').read_text(encoding='utf-8')
        self.assertNotIn('run_host(',source)


if __name__=='__main__':
    unittest.main()
