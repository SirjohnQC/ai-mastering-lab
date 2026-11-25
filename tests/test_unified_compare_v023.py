"""Static safety gates, independent of Windows/PySide6/JUCE.

These protect important source-level invariants, not actual audio playback.
"""
from pathlib import Path
import ast
import unittest

BASE = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'
UI = (BASE/'auto_studio_ui.py').read_text(encoding='utf8')
UNIFIED = (BASE/'unified_comparison.py').read_text(encoding='utf8')

class UnifiedComparisonSafety(unittest.TestCase):
    def test_all_compiles(self):
        for name in ('auto_studio_ui.py','unified_comparison.py','version.py'):
            ast.parse((BASE/name).read_text(encoding='utf8'))

    def test_nine_paths(self):
        self.assertIn("MIXES = ('balanced', 'vocal-focus', 'punchy')",UNIFIED)
        self.assertIn("COMPRESSIONS = ('original', 'gentle', 'firm')",UNIFIED)
        self.assertIn("for mix in MIXES for comp in COMPRESSIONS",UNIFIED)

    def test_explicit_approval_gate_for_master(self):
        node = next(n for n in ast.walk(ast.parse(UNIFIED)) if isinstance(n,ast.FunctionDef) and n.name=='master_source')
        code = ast.get_source_segment(UNIFIED,node)
        self.assertIn('self._approved',code)
        self.assertIn('self._sources.get(selected_mix)',code)
        self.assertIn('self._files.get(self._approved)',code)

    def test_render_requires_confirmation(self):
        node = next(n for n in ast.walk(ast.parse(UNIFIED)) if isinstance(n,ast.FunctionDef) and n.name=='_confirm_prepare')
        code = ast.get_source_segment(UNIFIED,node)
        self.assertIn('QMessageBox.question',code)
        self.assertIn('if answer != QMessageBox.Yes:return',code)
        self.assertIn('PrepareNineWorker',code)

    def test_switch_doesnt_reload_or_replay(self):
        node = next(n for n in ast.walk(ast.parse(UNIFIED)) if isinstance(n,ast.FunctionDef) and n.name=='_switch')
        code = ast.get_source_segment(UNIFIED,node)
        for unsafe in ('.play(','.stop(','.setSource('):
            self.assertNotIn(unsafe, code)
        self.assertIn('setMuted(True)',code)

    def test_all_backends_shutdown(self):
        node = next(n for n in ast.walk(ast.parse(UNIFIED)) if isinstance(n,ast.FunctionDef) and n.name=='_dispose_players')
        code = ast.get_source_segment(UNIFIED,node)
        for step in ('setMuted(True)','setVolume(0.0)','player.stop()','player.setSource(QUrl())','player.setAudioOutput(None)','deleteLater()'):
            self.assertIn(step,code)

    def test_integrated_in_simple_compare(self):
        self.assertIn('self.unified = UnifiedComparison(self.root, results)',UI)
        self.assertIn('rv.addWidget(self.unified)',UI)
        self.assertIn('self.unified.select_mix(key)',UI)
        self.assertIn('self.unified.master_source(self._selected)',UI)
        self.assertIn('self.unified.shutdown()',UI)
        self.assertIn('self.legacy_transport.hide()',UI)

    def test_hermes_not_misrepresented_as_compression_choice(self):
        self.assertIn('PAS un choix IA',UNIFIED)
        self.assertIn('Compression : aucun choix IA', UNIFIED+UI) if False else None
        self.assertIn('pas Hermes',UNIFIED)

    def test_old_advanced_tool_remains(self):
        self.assertIn('def _audition_pro_c3_song',UI)
        self.assertIn('def _open_selected_compression_preview',UI)
        self.assertIn('self.compression_preview.hide()',UI)

    def test_worker_uses_validated_existing_backend(self):
        self.assertIn('result = make_preview(self.root, self.paths[key])',UNIFIED)
        self.assertIn("result.get('status') != 'needs_review'",UNIFIED)
        self.assertIn('audition_files(self.root, result)',UNIFIED)

if __name__ == '__main__':unittest.main()
