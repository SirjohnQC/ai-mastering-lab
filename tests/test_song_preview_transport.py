"""AST-level regression checks; runtime Qt backend behavior requires Windows verification."""
import ast
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'src/mastering_lab/pro_c3_song_preview_ui.py'
SOURCE = PATH.read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)

def cls(name):
    return next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == name)

def method(type_name, name):
    return next(n for n in cls(type_name).body if isinstance(n, ast.FunctionDef) and n.name == name)

def calls(func):
    return sorted((n for n in ast.walk(func) if isinstance(n, ast.Call)), key=lambda node: (node.lineno, node.col_offset))

def attrcalls(func):
    return {ast.unparse(n.func) for n in calls(func) if isinstance(n.func, ast.Attribute)}

class TransportSafetyTests(unittest.TestCase):
    def test_stop_releases_media_and_mutes(self):
        found = attrcalls(method('SongCompressionPreviewDialog', 'stop'))
        self.assertIn('self.player.stop', found)
        self.assertIn('self.player.setSource', found)
        self.assertIn('self.output.setMuted', found)
    def test_stop_cancels_pending_autoplay(self):
        source = ast.unparse(method('SongCompressionPreviewDialog', 'stop'))
        self.assertIn('self.pending_play = False', source)
        self.assertIn('self.pending_position = None', source)
    def test_window_close_and_escape_shutdown_audio(self):
        self.assertIn('self.before_close', ast.unparse(method('SafePreviewDialog','closeEvent')))
        self.assertIn('self.before_close', ast.unparse(method('SafePreviewDialog','reject')))
        found = attrcalls(method('SongCompressionPreviewDialog','_shutdown_audio'))
        self.assertIn('self.stop', found)
        self.assertIn('self.player.setAudioOutput', found)
    def test_play_after_stop_reloads_source(self):
        source = ast.unparse(method('SongCompressionPreviewDialog', 'toggle'))
        self.assertIn('self.player.source().isEmpty()',source)
        self.assertIn('self.switch(selected)',source)
    def test_heart_is_persisted_before_marking(self):
        func = method('SongCompressionPreviewDialog','choose_preference')
        calls_in_order = [ast.unparse(n.func) for n in calls(func) if isinstance(n.func,(ast.Name,ast.Attribute))]
        self.assertLess(calls_in_order.index('save_choice'),calls_in_order.index('self._update_hearts'))
    def test_heart_has_selected_visual_and_reset(self):
        source = ast.unparse(method('SongCompressionPreviewDialog','_update_hearts'))
        self.assertIn('button.setChecked(chosen)',source)
        self.assertIn('♥ ',source)
        self.assertIn('♡ ',source)
        self.assertIn('setStyleSheet',source)
        self.assertIn('self._update_hearts()',ast.unparse(method('SongCompressionPreviewDialog','pick_and_render')))
    def test_does_not_unlock_auto_produce(self):
        self.assertNotIn('automatic_compression_enabled = True',SOURCE)
        self.assertNotIn('use_for_hermes = True',SOURCE)

if __name__ == '__main__': unittest.main()
