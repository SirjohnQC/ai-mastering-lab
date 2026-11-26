"""v0.25.8 album A/B selection must follow clicked song, not old list currentIndex."""
from __future__ import annotations
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'


class AlbumABSelectionTests(unittest.TestCase):
    def test_python_parses(self):
        ast.parse((ROOT/'album_studio_ui.py').read_text(encoding='utf-8'))
        ast.parse((ROOT/'version.py').read_text(encoding='utf-8'))

    def test_clickable_song_card_selects_by_stable_path(self):
        code=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        for snippet in (
            'class AlbumSelectableCard(QFrame):',
            'self._select_callback()',
            'AlbumSelectableCard(lambda source=path: self._select_song(source))',
            'self.track_list.setCurrentItem(item)',
            'name.setAttribute(Qt.WA_TransparentForMouseEvents, True)',
            'detail.setAttribute(Qt.WA_TransparentForMouseEvents, True)',
        ):
            self.assertIn(snippet,code)

    def test_ab_dialog_uses_explicit_chosen_song_not_first_item(self):
        code=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        for snippet in (
            "ab_track_button=QPushButton('♫ A/B')",
            'lambda _, source=path: self._open_ab_for_song(source)',
            'self._open_ab_for_song(source)',
            "self._album_track_for_path(source)",
            'self._intelligence_report[\'tracks\'][index]',
            "dlg.setWindowTitle('Album A/B · '+row['title'])",
        ):
            self.assertIn(snippet,code)
        tree=ast.parse(code)
        main=next(n for n in ast.walk(tree)
                  if isinstance(n,ast.ClassDef) and n.name=='AlbumStudioPage')
        op=next(n for n in main.body
                if isinstance(n,ast.FunctionDef) and n.name=='_open_ab_for_song')
        body=ast.get_source_segment(code,op)
        self.assertNotIn('self.track_list.currentItem()',body)
        self.assertIn('self._ab_track_ready(source)',body)

    def test_switching_qc_eligibility_gated_and_selection_survives_refresh(self):
        code=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn("row.get('status')!='qc_pass'",code)
        self.assertIn("report_rows[index].get('status')=='measured'",code)
        self.assertIn('selected_path=previous.data(Qt.UserRole)',code)
        self.assertIn('if item.data(Qt.UserRole)==selected_path:',code)
        self.assertIn('self.track_list.setCurrentItem(item)',code)

    def test_not_disrupting_drag_and_drop(self):
        code=(ROOT/'album_studio_ui.py').read_text(encoding='utf-8')
        self.assertIn('class AlbumDragHandle(QLabel):',code)
        self.assertIn('self.track_list.orderRequested.connect(self._on_song_card_drop)',code)
        self.assertIn('self._save()',code)


if __name__=='__main__':
    unittest.main()
