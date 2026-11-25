import json
import tempfile
import unittest
from pathlib import Path
from mastering_lab.pro_c3_calibration import calibration_summary, read_calibration_report, inspect_and_save


class CalibrationReport211(unittest.TestCase):
    def test_summary_and_legacy_support(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / 'settings' / 'pro_c3_calibration.json'
            path.parent.mkdir()
            path.write_text(json.dumps({'schema_version': 1, 'plugin': 'FabFilter Pro-C 3',
                'candidates': {'ratio': [{'index': 7, 'name': 'Ratio', 'normalized_value': 0.2}]},
                'required_status': {'ratio': 'candidate_only'}, 'ready_to_render': False}))
            result = read_calibration_report(root)
            summary = calibration_summary(result)
            self.assertIn('Ratio : candidate_only', summary)
            self.assertIn('NON CALIBRÉ', summary)

    def test_v2_keeps_metadata_without_render(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            host = root / 'host.exe'; host.touch()
            plugin = root / 'FabFilter Pro-C 3.vst3'; plugin.mkdir()
            calls = []
            def runner(host_path, command, **kw):
                calls.append(command)
                return {'name': 'FabFilter Pro-C 3', 'parameters': [
                    {'name': 'Threshold', 'index': 4, 'value': 0.44, 'automatable': True},
                    {'name': 'Ratio', 'index': 5, 'value': 0.12, 'automatable': True},
                    {'name': 'Attack', 'index': 6, 'value': 0.33, 'automatable': True},
                    {'name': 'Release', 'index': 7, 'value': 0.54, 'automatable': True}]}
            data = inspect_and_save(root, host=host, plugin=plugin, runner=runner)
            self.assertEqual(calls, ['inspect'])
            self.assertEqual(data['schema_version'], 2)
            self.assertFalse(data['ready_to_render'])
            self.assertFalse(data['mapping_verified'])
            saved = read_calibration_report(root)
            self.assertEqual(saved['parameter_metadata'][1]['normalized_value'], .12)

    def test_missing_and_unknown_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(FileNotFoundError):
                read_calibration_report(root)
            (root / 'settings').mkdir()
            (root / 'settings' / 'pro_c3_calibration.json').write_text('{"schema_version": 55}')
            with self.assertRaises(ValueError):
                read_calibration_report(root)

if __name__ == '__main__':
    unittest.main()
