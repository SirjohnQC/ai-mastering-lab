"""v0.25.7 regression tests for reference selection before QC and UI layout."""
import ast
import tempfile
import unittest
from pathlib import Path

from mastering_lab.album_project import empty_project, save_project, load_project

ROOT=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'


class AlbumReferencePickerLayoutTests(unittest.TestCase):
    def test_waiting_reference_selection_persists_in_project(self):
        project=empty_project()
        project['tracks']=[
            {'path':'C:/album/SongA/stems','title':'SongA','kind':'stems',
             'status':'waiting','result':None,'error':''},
            {'path':'C:/album/SongB/stems','title':'SongB','kind':'stems',
             'status':'waiting','result':None,'error':''},
        ]
        project['reference_source']=project['tracks'][1]['path']
        project['album_reference_mode']='album'
        project['external_reference_wav']='C:/another/reference.wav'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'album_project.json'
            save_project(path,project)
            loaded=load_project(path)
            self.assertEqual(loaded['reference_source'],project['tracks'][1]['path'])
            self.assertEqual(loaded['album_reference_mode'],'album')
            self.assertEqual(loaded['external_reference_wav'],'C:/another/reference.wav')

    def test_ui_has_selectable_waiting_tracks_and_restores_selection(self):
        source=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        ast.parse(source)
        self.assertIn("track.get('title','') + ('' if available else ' · à produire')",source)
        self.assertIn("if track['path'] == selected_path:",source)
        self.assertNotIn('self.reference_picker.model().item(item_index).setEnabled(False)',source)
        self.assertIn("self.project['album_reference_mode']='album'",source)
        self.assertIn("self.project['album_reference_mode']='external'",source)
        self.assertIn("if self._reference_mode()=='external' else None",source)

    def test_workflow_distinguishes_choice_from_qc_eligibility(self):
        source=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn("if row.get('status')!='qc_pass' or result.get('status')!='qc_pass':",source)
        self.assertIn('Référence sélectionnée',source)
        self.assertIn('prémix guidé par les préférences habituelles.',source)
        self.assertIn('external=Path(candidate)',source)
        self.assertIn('self.compare_album_btn.setEnabled(ready and not self._busy()',source)

    def test_list_receives_space_and_analysis_is_collapsible(self):
        source=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('self.track_list.setMinimumHeight(280)',source)
        self.assertIn('layout.addWidget(self.track_list, 3)',source)
        self.assertIn('self.consistency_detail.setMaximumHeight(88)',source)
        self.assertIn('self.more_results_btn.toggled.connect(self._toggle_results)',source)
        self.assertIn('self.more_results_btn.setVisible(len(lines)>2 and measured>0)',source)

    def test_qc_report_not_reset_by_picker_refresh(self):
        source=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('if self._intelligence_report is None:\n            self.consistency_status.setText(self._reference_message())',source)


if __name__ == '__main__':
    unittest.main()
