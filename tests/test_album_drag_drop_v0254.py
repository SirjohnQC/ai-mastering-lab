"""v0.25.4 — album drag-and-drop must preserve complete track/QC records."""
from __future__ import annotations

import ast
import copy
from pathlib import Path
import tempfile
import unittest

from mastering_lab.album_project import reorder_tracks, save_project, load_project, album_summary

ROOT=Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'


def project():
    return {
        'schema':1, 'album':'The EP', 'reference_source':'C:/master-ref.wav',
        'external_reference_wav':'C:/other/reference.wav',
        'tracks':[
            {'path':f'C:/songs/{n}.wav','kind':'stereo','title':n,
             'status':'qc_pass','error':'',
             'result':{'status':'qc_pass','file':f'C:/masters/{n}.wav',
                       'output_lufs':-14.0-i,'output_true_peak_dbtp':-1.2}}
            for i,n in enumerate(('first','second','third'))
        ]
    }


class DragDropAlbumOrderTests(unittest.TestCase):
    def test_reorder_moves_full_track_with_qc_and_external_reference_intact(self):
        original=project()
        original_tracks=copy.deepcopy(original['tracks'])
        keys=[row['path'] for row in original_tracks]
        reordered=reorder_tracks(original,[keys[2],keys[0],keys[1]])
        self.assertIs(original,reordered)
        self.assertEqual([row['title'] for row in original['tracks']],
                         ['third','first','second'])
        self.assertEqual(original['tracks'][0],original_tracks[2])
        self.assertEqual(original['tracks'][0]['result']['file'],
                         'C:/masters/third.wav')
        self.assertEqual(original['external_reference_wav'],
                         'C:/other/reference.wav')
        self.assertEqual(original['reference_source'],'C:/master-ref.wav')

    def test_missing_duplicate_and_extra_paths_fail_without_mutation(self):
        for proposed in (
            ['C:/songs/first.wav','C:/songs/second.wav'],
            ['C:/songs/first.wav']*3,
            ['C:/songs/first.wav','C:/songs/second.wav','C:/songs/unknown.wav'],
        ):
            p=project()
            before=copy.deepcopy(p)
            with self.assertRaises(ValueError):
                reorder_tracks(p,proposed)
            self.assertEqual(p,before)

    def test_order_survives_project_save_load_and_album_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            p=project()
            keys=[r['path'] for r in p['tracks']]
            reorder_tracks(p,[keys[1],keys[2],keys[0]])
            source=Path(temp)/'album_project.json'
            save_project(source,p)
            restored=load_project(source)
            self.assertEqual([r['title'] for r in restored['tracks']],
                             ['second','third','first'])
            self.assertEqual(restored['external_reference_wav'],
                             p['external_reference_wav'])
            self.assertEqual([e['title'] for e in album_summary(restored)['tracks']],
                             ['second','third','first'])

    def test_drag_handle_and_model_wiring_are_present(self):
        source=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        ast.parse(source)
        for expected in (
            'class AlbumOrderList(QListWidget):',
            'class AlbumDragHandle(QLabel):',
            'self.track_list.model().rowsMoved.connect(self._schedule_track_reorder)',
            'QTimer.singleShot(0, self._commit_track_reorder)',
            'reorder_tracks(self.project, ordered)',
            'self._save()',
            'drag_handle.item = item',
            'self.track_list.setDragDropMode(',
            'QAbstractItemView.InternalMove if not self._busy()',
        ):
            self.assertIn(expected,source)
        # There are no longer one-click move-up/move-down card buttons.
        self.assertNotIn("('↑', lambda",source)
        self.assertNotIn("('↓', lambda",source)


if __name__ == '__main__':
    unittest.main()
