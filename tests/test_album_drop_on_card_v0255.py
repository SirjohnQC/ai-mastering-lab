"""v0.25.5: dropping ON an existing card reorders songs, never replaces them."""
from __future__ import annotations
import ast
from copy import deepcopy
from pathlib import Path
import unittest

from mastering_lab.album_project import move_track_onto

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


def project():
    return {'schema':1,'external_reference_wav':'C:/ref.wav',
            'tracks':[{'path':f'C:/{n}.wav','title':n,
                       'status':'qc_pass','result':{'file':f'C:/masters/{n}.wav'}}
                      for n in ('A','B','C','D')]}


class DropOnCardTests(unittest.TestCase):
    def test_last_song_on_first_card(self):
        p=project()
        original=deepcopy(p)
        self.assertTrue(move_track_onto(p,'C:/D.wav','C:/A.wav'))
        self.assertEqual([t['title'] for t in p['tracks']],['D','A','B','C'])
        self.assertEqual(p['tracks'][0],original['tracks'][3])
        self.assertEqual(p['external_reference_wav'],'C:/ref.wav')

    def test_first_song_on_last_card(self):
        p=project()
        self.assertTrue(move_track_onto(p,'C:/A.wav','C:/D.wav'))
        self.assertEqual([t['title'] for t in p['tracks']],['B','C','D','A'])

    def test_drop_onto_same_card_is_noop(self):
        p=project()
        snapshot=deepcopy(p)
        self.assertFalse(move_track_onto(p,'C:/B.wav','C:/B.wav'))
        self.assertEqual(p,snapshot)

    def test_missing_target_or_source_rejected_without_mutation(self):
        for src,dst in (('missing','C:/B.wav'),('C:/B.wav','missing')):
            p=project()
            snapshot=deepcopy(p)
            with self.assertRaises(ValueError):
                move_track_onto(p,src,dst)
            self.assertEqual(p,snapshot)

    def test_qt_card_drop_interaction_and_syntax(self):
        code=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        ast.parse(code)
        for needle in (
            'orderRequested = Signal(str, str)',
            'self.orderRequested.emit(source_path, target_path)',
            'target = self.itemAt(event.position().toPoint())',
            'self._highlight_target(target)',
            'self.setDropIndicatorShown(False)',
            'self.track_list.orderRequested.connect(self._on_song_card_drop)',
            'QTimer.singleShot(0, lambda: self._move_song_onto(source_path, target_path))',
            'move_track_onto(self.project, source_path, target_path)',
            'self._save()',
        ):
            self.assertIn(needle,code)


if __name__=='__main__':
    unittest.main()
