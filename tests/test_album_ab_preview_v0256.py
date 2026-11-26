"""v0.25.6: non-destructive Album A/B level preview gating and UI wiring."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from mastering_lab.album_ab_preview import proposal

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


class AlbumABPreviewTests(unittest.TestCase):
    def test_quieter_song_can_raise_level_only_with_peak_headroom(self):
        p=proposal({'status':'measured','lufs_delta':-2.0,
                    'true_peak_dbtp':-2.9},Path('unused.wav'))
        self.assertEqual(p['gain_db'],1.0)
        self.assertEqual(p['kind'],'level_only')
        self.assertNotIn('eq_gain',p)

    def test_louder_song_gets_conservative_attenuation(self):
        p=proposal({'status':'measured','lufs_delta':2.4,
                    'true_peak_dbtp':-1.4},Path('unused.wav'))
        self.assertEqual(p['gain_db'],-1.0)

    def test_no_safe_boost_when_true_peak_has_no_headroom(self):
        with self.assertRaisesRegex(ValueError,'headroom'):
            proposal({'status':'measured','lufs_delta':-2.0,
                      'true_peak_dbtp':-1.1},Path('unused.wav'))

    def test_small_difference_or_unapproved_or_invalid_rejected(self):
        for track in (
            {'status':'measured','lufs_delta':.3,'true_peak_dbtp':-1.5},
            {'status':'reference','lufs_delta':-2.,'true_peak_dbtp':-2.},
            {'status':'measured','lufs_delta':-2.,'true_peak_dbtp':-.8},
            {'status':'measured','lufs_delta':float('nan'),'true_peak_dbtp':-2.},
        ):
            with self.assertRaises(ValueError):
                proposal(track,Path('unused.wav'))

    def test_all_new_code_parses_and_ab_player_is_single_shared_transport(self):
        for name in ('album_ab_preview.py','album_studio_ui.py','version.py'):
            ast.parse((ROOT/name).read_text(encoding='utf-8'))
        ui=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        for needle in (
            'class AlbumABDialog(QDialog):','self.audio=QAudioOutput(self)',
            'self.player=QMediaPlayer(self)',
            "self.original_button.clicked.connect(lambda:self._switch('original'))",
            "self.adjusted_button.clicked.connect(lambda:self._switch('adjusted'))",
            'self.player.setPosition(pos)',
            'self.approve_button.clicked.connect(self._approve)',
            "self.ab_button.clicked.connect(self._open_ab)",
            "self.export_dir/'ab_previews'",
        ):
            self.assertIn(needle,ui)

    def test_preview_worker_does_not_run_on_ui_thread(self):
        ui=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('class AlbumABRenderWorker(QThread):',ui)
        self.assertIn('worker.start()',ui)
        self.assertIn('self.worker is not None:',ui)

    def test_engine_never_calls_mastering_or_eq_or_overwrites_source(self):
        code=(ROOT/'album_ab_preview.py').read_text(encoding='utf-8')
        for forbidden in ('master_song(', 'apply_eq(', 'replace(master)', 'os.replace(master', 'requests.post('):
            self.assertNotIn(forbidden,code)
        self.assertIn("'status':'preview_only'",code)
        self.assertIn("'approved':False",code)
        self.assertIn('actual_tp>TRUE_PEAK_CEILING',code)
        self.assertIn("'-c:a','pcm_s24le'",code)


if __name__=='__main__':
    unittest.main()
