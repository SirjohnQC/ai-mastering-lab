import ast
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / 'src/mastering_lab/auto_studio_ui.py').read_text(encoding='utf-8')
MIXER = (ROOT / 'src/mastering_lab/stem_plus_ui.py').read_text(encoding='utf-8')

class PatchTests(unittest.TestCase):
    def test_selection_list_is_present_and_connected(self):
        self.assertIn('self._refresh_stem_list()', UI)
        self.assertIn('remove.clicked.connect', UI)
        self.assertIn('remove_stem_from_selection(file_path)', UI)
        self.assertIn('self.stem_list_scroll.setMaximumHeight(226)', UI)

    def test_original_wavs_are_not_deleted(self):
        cls = next(x for x in ast.parse(MIXER).body if isinstance(x, ast.ClassDef) and x.name == 'StemPlusPage')
        method = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == 'remove_stem_from_selection')
        code = ast.get_source_segment(MIXER, method)
        self.assertNotIn('.unlink(', code)
        self.assertNotIn('.remove(', code)
        self.assertIn("'tracks': survivors", code)
        self.assertIn('self._remember_selection', code)

    def test_navigation_and_reset(self):
        self.assertIn('self._can_change_music()', UI)
        self.assertIn('self._load_config(candidate)', MIXER)
        self.assertIn('self.audioLoaded.emit(0', MIXER)
        self.assertIn('self.produce_btn.setEnabled(count > 0)', UI)

if __name__ == '__main__':
    unittest.main()
