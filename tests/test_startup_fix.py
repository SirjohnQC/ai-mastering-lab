"""Regression: opening Compare must not reference an undefined EQ preference variable."""
import ast
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / 'src/mastering_lab/auto_studio_ui.py'

class StartupFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(FILE.read_text(encoding='utf-8'))

    def test_single_mix_worker_does_not_reference_unknown_eq_preferences_path(self):
        worker = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == 'SingleMixEvaluationWorker')
        init = next(n for n in worker.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
        self.assertNotIn('eq_preferences_path', [n.id for n in ast.walk(init) if isinstance(n, ast.Name)])

    def test_fx_worker_still_accepts_eq_preferences_path(self):
        worker = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == 'AIFXWorker')
        init = next(n for n in worker.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
        self.assertIn('eq_preferences_path', [a.arg for a in init.args.kwonlyargs])

    def test_source_compiles(self):
        compile(FILE.read_text(encoding='utf-8'), str(FILE), 'exec')

if __name__ == '__main__':
    unittest.main()
