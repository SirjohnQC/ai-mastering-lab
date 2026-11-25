from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'src/mastering_lab/auto_studio_ui.py').read_text(encoding='utf-8')

class StartupLabelTests(unittest.TestCase):
    def test_python_parses(self):
        ast.parse(SOURCE)

    def test_no_nonexistent_label_signal(self):
        self.assertNotIn('fx_status.textChanged', SOURCE)

    def test_mirror_preserves_both_status_labels(self):
        self.assertIn('def _set_fx_status(self, message):', SOURCE)
        self.assertIn('self.fx_status.setText(message)', SOURCE)
        self.assertIn('self._calibration_status.setText(message)', SOURCE)
        self.assertIn("self._set_fx_status('✓ Grille multipoint sauvegardée", SOURCE)

if __name__ == '__main__':
    unittest.main()
