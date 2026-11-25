import json
import tempfile
import unittest
from pathlib import Path
from mastering_lab.pro_c3_calibration import discover_mapping, displayed_value_evidence, calibration_summary, read_calibration_report


class CalibrationLabTests(unittest.TestCase):
    def parameters(self):
        return [
            {'index': 1, 'name': 'Threshold', 'value': .73, 'text': '-18.0 dB', 'automatable': True},
            {'index': 4, 'name': 'Ratio', 'value': .56, 'text': '4:1', 'automatable': True},
            {'index': 7, 'name': 'Attack', 'value': .14, 'text': '10.0 ms', 'automatable': True},
            {'index': 8, 'name': 'Release', 'value': .28, 'text': '120 ms', 'automatable': True},
        ]

    def test_detects_display_text_with_units(self):
        mapping = discover_mapping(self.parameters())
        self.assertTrue(all(v == 'displayed_unit_detected' for v in displayed_value_evidence(mapping).values()))
        self.assertFalse(mapping['ready_to_render'])
        self.assertFalse(mapping['mapping_verified'])

    def test_missing_text_requires_review(self):
        p = self.parameters()
        del p[2]['text']
        self.assertEqual(displayed_value_evidence(discover_mapping(p))['attack'], 'requires_manual_review')

    def test_bad_indices_ignored(self):
        p = self.parameters()
        p[0]['index'] = True
        self.assertEqual(discover_mapping(p)['required_status']['threshold'], 'missing')

    def test_invalid_numeric_not_stored(self):
        p = self.parameters()
        p[1]['value'] = float('nan')
        self.assertIsNone(discover_mapping(p)['candidates']['ratio'][0]['normalized_value'])

    def test_report_never_claims_ready(self):
        r = discover_mapping(self.parameters())
        msg = calibration_summary({'plugin':'Pro-C 3', 'parameter_count': 237, **r})
        self.assertIn('NON CALIBRÉ', msg)
        self.assertIn('4:1', msg)

    def test_old_schema_readable(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'settings' / 'pro_c3_calibration.json'
            path.parent.mkdir()
            for v in [1,2,3]:
                path.write_text(json.dumps({'schema_version':v}))
                self.assertEqual(read_calibration_report(d)['schema_version'], v)

if __name__ == '__main__':
    unittest.main()
