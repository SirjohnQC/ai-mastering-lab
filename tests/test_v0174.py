"""Regression checks for v0.17.4 master listening UI, runnable without Qt."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'src/mastering_lab/auto_studio_ui.py').read_text(encoding='utf-8')
MODULE = ast.parse(SOURCE)
PAGE = next(node for node in MODULE.body if isinstance(node, ast.ClassDef) and node.name == 'AutoStudioPage')
METHODS = {item.name: item for item in PAGE.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}

def method(name):
    return ast.get_source_segment(SOURCE, METHODS[name])

class MasterReviewTests(unittest.TestCase):
    def test_master_player_has_waveform_seek_and_transport(self):
        ui = method('_init_ui')
        for text in ('master_waveform', 'clickedPosition.connect(self._master_seek_waveform)',
                     'master_seek.sliderReleased.connect(self._master_seek_released)',
                     'master_stop.clicked.connect(self._stop_master_preview)',
                     'master_clock', 'master_player_panel.hide()'):
            self.assertIn(text, ui)

    def test_pause_is_based_on_actual_qt_state(self):
        self.assertIn('QMediaPlayer.PlayingState', method('_listen_master'))
        self.assertIn('player.pause()', method('_listen_master'))
        self.assertIn('player.play()', method('_listen_master'))
        self.assertIn('playbackStateChanged.connect(self._master_playback_state_changed)', method('_master_player'))
        self.assertIn('self.master_listen.setText', method('_master_playback_state_changed'))

    def test_waveform_is_async_and_discarded_for_new_sources(self):
        self.assertIn('WaveformLoader(token', method('_prepare_master_preview'))
        self.assertIn('job.start()', method('_prepare_master_preview'))
        self.assertIn('token == str(self._master_waveform_token)', method('_master_waveform_ready'))
        self.assertIn('job.requestInterruption()', method('_reset_master_preview'))

    def test_mastering_remains_manual(self):
        self.assertNotIn('self._start_master(', method('_continue_mastering'))
        self.assertNotIn('self._start_master(', method('_open_master_stage'))
        self.assertIn('self.master_run.clicked.connect(self._start_master)', method('_init_ui'))

    def test_preview_loaded_only_after_master_complete(self):
        self.assertIn("self._prepare_master_preview(result.get('file'))", method('_master_done'))
        self.assertIn('self._reset_master_preview()', method('_start_master'))
        self.assertIn('self._reset_master_preview()', method('_audio_loaded'))

    def test_time_formatter(self):
        func = METHODS['_format_master_clock']
        code = compile(ast.Module(body=[func], type_ignores=[]), '<formatter>', 'exec')
        scope = {}
        exec(code, scope)
        f = scope['_format_master_clock']
        self.assertEqual(f(0), '00:00')
        self.assertEqual(f(61000), '01:01')
        self.assertEqual(f(3599999), '59:59')

if __name__ == '__main__':
    unittest.main()
