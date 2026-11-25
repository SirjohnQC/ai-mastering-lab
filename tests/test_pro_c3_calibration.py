import json
import tempfile
import unittest
from pathlib import Path
from mastering_lab.pro_c3_calibration import discover_mapping, inspect_and_save


class ProC3CalibrationTests(unittest.TestCase):
    def test_exact_parameter_names_are_candidates_not_verified(self):
        result = discover_mapping([{'index': 7, 'name': 'Threshold', 'automatable': True},
                                   {'index': 8, 'name': 'Ratio', 'automatable': True},
                                   {'index': 9, 'name': 'Attack', 'automatable': True},
                                   {'index': 10, 'name': 'Release', 'automatable': True}])
        self.assertEqual(result['required_status']['ratio'], 'candidate_only')
        self.assertFalse(result['mapping_verified'])
        self.assertFalse(result['ready_to_render'])

    def test_duplicate_is_ambiguous(self):
        result = discover_mapping([{'name': 'Threshold'}, {'name': 'Threshold'}])
        self.assertEqual(result['required_status']['threshold'], 'ambiguous')
        self.assertEqual(result['required_status']['attack'], 'missing')

    def test_non_automatable_not_used(self):
        result = discover_mapping([{'name': 'Ratio', 'automatable': False}])
        self.assertEqual(result['required_status']['ratio'], 'missing')

    def test_invalid_metadata_rejected(self):
        with self.assertRaises(ValueError):
            discover_mapping('not a list')

    def test_only_inspect_and_persist_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            host = root / 'host.exe'; host.touch()
            plugin = root / 'FabFilter Pro-C 3.vst3'; plugin.mkdir()
            calls = []
            def runner(h, command, **kwargs):
                calls.append((command, kwargs))
                return {'name': 'FabFilter Pro-C 3', 'parameters': [
                    {'name': 'Threshold', 'index': 3, 'automatable': True},
                    {'name': 'Ratio', 'index': 4, 'automatable': True},
                    {'name': 'Attack', 'index': 5, 'automatable': True},
                    {'name': 'Release', 'index': 6, 'automatable': True},
                ]}
            result = inspect_and_save(root, host=host, plugin=plugin, runner=runner)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], 'inspect')
            self.assertNotIn('parameter_changes', calls[0][1])
            saved = json.loads((root / 'settings' / 'pro_c3_calibration.json').read_text('utf-8'))
            self.assertFalse(saved['ready_to_render'])
            self.assertNotIn('report_path', saved)

    def test_wrong_plugin_does_not_save_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            host = root / 'host.exe'; host.touch()
            plugin = root / 'FabFilter Pro-C 3.vst3'; plugin.mkdir()
            with self.assertRaises(ValueError):
                inspect_and_save(root, host=host, plugin=plugin, runner=lambda *_a,**_kw: {'name':'Fake', 'parameters': []})
            self.assertFalse((root / 'settings' / 'pro_c3_calibration.json').exists())

if __name__ == '__main__':
    unittest.main()
