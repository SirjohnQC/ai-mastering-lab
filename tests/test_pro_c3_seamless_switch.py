"""Structural regression tests: realtime PySide6 requires Windows manual testing."""
from pathlib import Path
import ast
import unittest

UI = (Path(__file__).resolve().parents[1] / 'src/mastering_lab/pro_c3_song_preview_ui.py').read_text(encoding='utf8')
TREE = ast.parse(UI)
CLS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'SongCompressionPreviewDialog')

def method(name):
    return next(n for n in CLS.body if isinstance(n, ast.FunctionDef) and n.name == name)

class SeamlessSwitchTests(unittest.TestCase):
    def test_three_dedicated_players_and_outputs(self):
        init = ast.get_source_segment(UI, method('__init__'))
        self.assertIn("for key in ('original', 'gentle', 'firm'):", init)
        self.assertIn('self.players[key] = player', init)
        self.assertIn('self.outputs[key] = output', init)

    def test_switch_never_stops_reloads_or_restarts_player(self):
        sw = ast.get_source_segment(UI, method('switch'))
        for forbidden in ('setSource(', '.stop(', '.play('):
            self.assertNotIn(forbidden, sw)
        self.assertIn('self._select_audible()', sw)
        self.assertIn('self.outputs[old].setMuted(True)', sw)

    def test_all_three_run_together(self):
        beginning = ast.get_source_segment(UI, method('_begin_playback'))
        self.assertIn('for key, player in self.players.items():', beginning)
        self.assertIn('player.play()', beginning)
        self.assertIn('self._sync_timer.start()', beginning)

    def test_stop_releases_all_streams(self):
        stopping = ast.get_source_segment(UI, method('stop'))
        self.assertIn('self._sync_timer.stop()', stopping)
        self.assertIn('player.stop()', stopping)
        self.assertIn('player.setSource(QUrl())', stopping)
        self.assertIn('self.outputs[key].setMuted(True)', stopping)

    def test_close_releases_every_output(self):
        closing = ast.get_source_segment(UI, method('_shutdown_audio'))
        self.assertIn('self.stop()', closing)
        self.assertIn('player.setAudioOutput(None)', closing)

    def test_all_seek_together(self):
        seek = ast.get_source_segment(UI, method('_seek_all'))
        self.assertIn('for player in self.players.values():', seek)
        self.assertIn('player.setPosition(pos)', seek)

    def test_matching_and_heart_preserved(self):
        self.assertIn('preview_volume(self.playback_matching, key, enabled)', UI)
        self.assertIn('self._update_hearts()', UI)
        self.assertIn('self.selected_preference = kind', UI)

if __name__ == '__main__': unittest.main()
