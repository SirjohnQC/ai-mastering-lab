"""v0.24.4 regression: language switching preserves player, master and locale keys."""
from pathlib import Path
import ast
import unittest

from mastering_lab.ui_language import TRANSLATIONS, tr

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'


class LanguageConsistencyTests(unittest.TestCase):
    def test_dictionary_keys_match(self):
        self.assertEqual(set(TRANSLATIONS['fr']),set(TRANSLATIONS['en']))
        for lang in ('fr','en'):
            for key in ('import_headline','producing_headline','master_caution',
                        'compare_ready_cached','compare_marker_title',
                        'compare_approval_default','compare_advice_heart'):
                self.assertTrue(tr(lang,key))
        self.assertIn('Pink',tr('en','compare_marker_title',variant='Gentle'))
        self.assertIn('repères',tr('fr','compare_review_count',count=2))

    def test_all_modified_python_files_parse(self):
        for filename in ('auto_studio_ui.py','unified_comparison.py',
                         'ui_language.py','version.py'):
            ast.parse((ROOT/filename).read_text(encoding='utf-8'))

    def test_ui_translation_reuses_existing_audio(self):
        code=(ROOT/'unified_comparison.py').read_text(encoding='utf-8')
        tree=ast.parse(code)
        translate=next(n for n in ast.walk(tree)
                       if isinstance(n,ast.FunctionDef) and n.name=='set_language')
        text=ast.get_source_segment(code,translate)
        self.assertIn('self._update_active_diagnostics()',text)
        for forbidden in ('_setup_players(', '_dispose_players(', 'self.approve(', 'make_preview('):
            self.assertNotIn(forbidden,text)

    def test_visible_import_produce_and_mastering_are_translated(self):
        code=(ROOT/'auto_studio_ui.py').read_text(encoding='utf-8')
        for key in ('import_headline','import_explanation','producing_headline',
                    'producing_safe','cancel_production','master_caution',
                    'master_preflight_running','master_preflight_error'):
            self.assertIn(f"'{key}'", code)
        self.assertIn("tr(self._language,'master_already')",code)
        self.assertIn('self._refresh_preflight_report()',code)

    def test_mastering_safety_and_heart_remain(self):
        code=(ROOT/'auto_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('self.unified.master_source(self._selected)',code)
        self.assertIn('self._go(3)',code)
        self.assertIn("APP_VERSION = '0.24.4'",
                      (ROOT/'version.py').read_text(encoding='utf-8'))

if __name__ == '__main__':
    unittest.main()
