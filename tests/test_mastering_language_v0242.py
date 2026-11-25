"""v0.24.2: check Mastering handoff and persistent FR/EN guided UI wiring."""
from __future__ import annotations
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'


class NavigationAndLanguageTests(unittest.TestCase):
    def test_all_changed_files_parse(self):
        for name in ('auto_studio_ui.py','unified_comparison.py','ui_language.py','version.py'):
            ast.parse((ROOT/name).read_text(encoding='utf-8'))

    def test_mastering_button_still_calls_preparation_and_navigation(self):
        code=(ROOT/'auto_studio_ui.py').read_text(encoding='utf-8')
        tree=ast.parse(code)
        methods={node.name:ast.get_source_segment(code,node)
                 for node in ast.walk(tree) if isinstance(node,ast.FunctionDef)}
        self.assertIn('self.continue_btn.clicked.connect(self._continue_mastering)',code)
        self.assertIn('self._prepare_mastering_navigation()',methods['_continue_mastering'])
        self.assertIn('QMessageBox.critical(',methods['_continue_mastering'])
        self.assertIn('self._go(3)',methods['_prepare_mastering_navigation'])
        self.assertIn('self.unified.master_source(self._selected)',methods['_prepare_mastering_navigation'])
        self.assertIn('self.unified._sources.get(self._selected)',methods['_selected_mix_path'])
        self.assertIn('self._approved', (ROOT/'unified_comparison.py').read_text(encoding='utf-8'))

    def test_completed_qthread_handle_is_safe_to_query(self):
        code=(ROOT/'unified_comparison.py').read_text(encoding='utf-8')
        tree=ast.parse(code)
        methods={node.name:ast.get_source_segment(code,node)
                 for node in ast.walk(tree) if isinstance(node,ast.FunctionDef)}
        self.assertIn('except RuntimeError:',methods['is_busy'])
        self.assertIn('self.worker = None',methods['is_busy'])
        self.assertIn('self.worker = None',methods['_worker_finished'])
        self.assertIn('worker.finished.connect(self._worker_finished)',code)
        self.assertIn('worker.finished.connect(worker.deleteLater)',code)

    def test_both_languages_have_all_keys(self):
        from mastering_lab.ui_language import TRANSLATIONS, tr
        self.assertEqual(set(TRANSLATIONS['fr']),set(TRANSLATIONS['en']))
        self.assertIn('Mastering',tr('fr','continue',mix='Balanced'))
        self.assertIn('Mastering',tr('en','continue',mix='Balanced'))
        self.assertIn('Source:',tr('en','source',name='demo.wav',variant='original'))
        self.assertIn('Source :',tr('fr','source',name='demo.wav',variant='original'))

    def test_language_change_does_not_recreate_audio(self):
        code=(ROOT/'unified_comparison.py').read_text(encoding='utf-8')
        tree=ast.parse(code)
        method=next(node for node in ast.walk(tree)
                    if isinstance(node,ast.FunctionDef) and node.name=='set_language')
        source=ast.get_source_segment(code,method)
        for forbidden in ('_setup_players(', 'make_preview(', '_dispose_players(',
                          'self.approve(', 'self._approved ='):
            self.assertNotIn(forbidden,source)
        self.assertIn('self.language_combo.currentIndexChanged.connect(self._change_language)',
                      (ROOT/'auto_studio_ui.py').read_text(encoding='utf-8'))

if __name__=='__main__':
    unittest.main()
