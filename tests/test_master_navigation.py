"""Regression guard: entering Mastering tab must not launch processing."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/mastering_lab/auto_studio_ui.py'

class MasterNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SRC.read_text(encoding='utf-8'))
        cls.page = next(node for node in cls.tree.body if isinstance(node, ast.ClassDef) and node.name == 'AutoStudioPage')

    @classmethod
    def method(cls, name):
        return next(node for node in cls.page.body if isinstance(node, ast.FunctionDef) and node.name == name)

    def test_navigation_never_calls_render_or_continue(self):
        method = self.method('_open_master_stage')
        called = [node.func.attr for node in ast.walk(method) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertNotIn('_start_master', called)
        self.assertNotIn('_continue_mastering', called)
        self.assertIn('_go', called)

    def test_continue_remains_explicit_entry_to_automatic_master(self):
        method = self.method('_continue_mastering')
        src = ast.get_source_segment(SRC.read_text(encoding='utf-8'),method)
        self.assertIn('QTimer.singleShot(0, self._start_master)', src)

    def test_manual_master_button_is_wired(self):
        src=SRC.read_text(encoding='utf-8')
        self.assertIn('self.master_run.clicked.connect(self._start_master)', src)

if __name__ == '__main__':
    unittest.main()
