"""Regression checks for the UI state-machine wiring (PySide GUI smoke test runs on Windows)."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CODE = (ROOT / 'src/mastering_lab/mix_compare_ui.py').read_text(encoding='utf-8')
TREE = ast.parse(CODE)
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'MixCompareDialog')
METHODS = {n.name: n for n in CLASS.body if isinstance(n, ast.FunctionDef)}

def body(name):
    node = METHODS[name]
    return ast.get_source_segment(CODE, node)

class TestGen2Flow(unittest.TestCase):
    def test_comparison_loaded_in_place(self):
        code = body('_open_gen2_comparison')
        self.assertIn('self._load_comparison_in_place(report_path)', code)
        self.assertNotIn('MixCompareDialog(', code)
        self.assertNotIn('QMessageBox.information', code)

    def test_gen2_restarts_automatic_analysis(self):
        code = body('_open_gen2_comparison')
        self.assertIn('QTimer.singleShot(150, self.start_automatic_analysis)', code)
        self.assertIn('if self._load_comparison_in_place(report_path):', code)

    def test_automatic_analysis_chains_dsp_hermes_lufs(self):
        self.assertIn('self._start_evaluation(True, use_vision=self._auto_vision_optin.isChecked())', body('start_automatic_analysis'))
        self.assertIn('self._start_loudness', body('_evaluation_done'))
        self.assertIn('self.automaticAnalysisFinished.emit(True', body('_loudness_done'))

    def test_next_generation_uses_actual_number(self):
        self.assertIn('generation + 1', body('_refresh_generation_label'))

    def test_reports_status_and_preserves_originals(self):
        self.assertIn('trois nouveaux WAV prêts', body('_open_gen2_comparison'))
        self.assertIn('self._comparison_source = Path(report_path).resolve()', body('_load_comparison_in_place'))
        self.assertIn('self._back_generation_btn.setVisible(parent is not None)', body('_refresh_generation_label'))

if __name__ == '__main__': unittest.main()
