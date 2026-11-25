"""Structural regression checks for the legacy optional Pro-C 3 Tools handoff.

These checks do not claim to exercise Qt or the JUCE Windows backend.
"""
from pathlib import Path
import ast
import unittest

SRC = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'


class StudioCompressionHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.studio = (SRC / 'auto_studio_ui.py').read_text(encoding='utf-8')
        cls.preview = (SRC / 'pro_c3_song_preview_ui.py').read_text(encoding='utf-8')
        ast.parse(cls.studio)
        ast.parse(cls.preview)

    def test_embedded_compare_replaces_popup_without_disabling_tools(self):
        self.assertIn('rv.addWidget(self.unified)', self.studio)
        self.assertIn('self.compression_preview.hide()', self.studio)
        self.assertIn("self.compression_preview.setEnabled(False)", self.studio)
        self.assertIn('def _open_selected_compression_preview(self):', self.studio)

    def test_handoff_uses_current_selected_mix(self):
        start = self.studio.index('    def _open_selected_compression_preview(')
        end = self.studio.index('    def _audition_pro_c3_song(', start)
        method = self.studio[start:end]
        self.assertIn('source = self._selected_mix_path()', method)
        self.assertIn('initial_source=source', method)
        self.assertIn('dialog.exec()', method)
        self.assertNotIn('make_preview(', method)

    def test_existing_tools_dialog_still_works(self):
        start = self.studio.index('    def _audition_pro_c3_song(')
        end = self.studio.index('    def _show_pro_c3_validation_report(', start)
        self.assertIn('SongCompressionPreviewDialog(self.root, self)', self.studio[start:end])

    def test_preview_remains_confirmed_and_sandboxed(self):
        self.assertIn('if confirmation != QMessageBox.Yes:return', self.preview)
        self.assertIn('verify_source(filename)', self.preview)
        self.assertIn("self.worker = RenderWorker(self.root,filename,self.dialog)", self.preview)
        self.assertIn('self.initial_source', self.preview)

    def test_selection_changes_enabling(self):
        start = self.studio.index('    def _select(')
        end = self.studio.index('    def _toggle_play(',start)
        self.assertIn('self.compression_preview.setEnabled(self._selected_mix_path() is not None)',self.studio[start:end])

    def test_closing_invalidates_button(self):
        start = self.studio.index('    def _close_player(')
        end = self.studio.index('    def shutdown(', start)
        self.assertIn('self.compression_preview.setEnabled(False)', self.studio[start:end])

if __name__ == '__main__':
    unittest.main()
