"""v0.26.2 regression: A/B switches without reloading WAVs and shows active source."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


def method(class_name, method_name):
    code=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
    cls=next(n for n in ast.parse(code).body
             if isinstance(n,ast.ClassDef) and n.name==class_name)
    node=next(n for n in cls.body
              if isinstance(n,ast.FunctionDef) and n.name==method_name)
    return ast.get_source_segment(code,node)


class AlbumABContinuousPlaybackTests(unittest.TestCase):
    def test_every_changed_file_is_parseable(self):
        for name in ('album_studio_ui.py','version.py'):
            ast.parse((ROOT/name).read_text(encoding='utf-8'))

    def test_two_players_with_preloaded_sources(self):
        code=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('self.player=QMediaPlayer(self)',code)
        self.assertIn('self.preview_player=QMediaPlayer(self)',code)
        self.assertIn('self.audio=QAudioOutput(self)',code)
        self.assertIn('self.preview_audio=QAudioOutput(self)',code)
        self.assertIn("self.preview_player.setSource(QUrl.fromLocalFile(str(result['file'])))",code)
        self.assertIn('self.preview_player.mediaStatusChanged.connect(self._preview_status_changed)',code)

    def test_switch_never_replaces_wav_source(self):
        switch=method('AlbumABDialog','_switch')
        self.assertNotIn('setSource(',switch)
        self.assertIn('self.player.setPosition(pos)',switch)
        self.assertIn('self.preview_player.setPosition(pos)',switch)
        self.assertIn('self._audio_for(source).setVolume(0.0)',switch)
        self.assertIn('target.play()',switch)
        self.assertNotIn('previous.stop()',switch)

    def test_handoff_waits_for_target_playback_and_only_then_pauses_old(self):
        handoff=method('AlbumABDialog','_playback_changed')
        self.assertIn('self._pending_switch != source',handoff)
        self.assertIn('self._audio_for(source).setVolume(1.0)',handoff)
        self.assertIn('self._player_for(previous).pause()',handoff)
        self.assertIn('self.source=source',handoff)
        self.assertIn('self._update_active_indicator()',handoff)

    def test_active_identity_is_clearly_visible(self):
        code=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        for text in ('self.now_playing=QLabel(', 'EN ÉCOUTE : ',
                     'self.original_button.setStyleSheet(',
                     'self.adjusted_button.setStyleSheet(',
                     "self.original_button.setAccessibleName(",
                     "self.adjusted_button.setAccessibleName("):
            self.assertIn(text,code)

    def test_style_change_disables_old_b_and_unloads_it(self):
        mode=method('AlbumABDialog','_mode_changed')
        self.assertIn("self.preview=None",mode)
        self.assertIn("self.adjusted_button.setEnabled(False)",mode)
        self.assertIn("self.preview_player.stop()",mode)
        self.assertIn("self.preview_player.setSource(QUrl())",mode)

    def test_rapid_clicks_and_dialog_close_are_guarded(self):
        switch=method('AlbumABDialog','_switch')
        self.assertIn('Cancel a pending hand-off',switch)
        close=method('AlbumABDialog','closeEvent')
        self.assertIn('self.preview_player.stop()',close)
        self.assertIn('self.player.stop()',close)
        self.assertIn('if self.worker is not None:',close)


if __name__=='__main__':
    unittest.main()
