import ast
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / 'src/mastering_lab/auto_studio_ui.py'


def test_ui_python_parses():
    ast.parse(UI.read_text(encoding='utf-8'))


def test_import_step_is_a_button_not_label():
    source = UI.read_text(encoding='utf-8')
    assert 'action = QPushButton(text)' in source
    assert 'action.clicked.connect(self._show_import)' in source
    assert "self.change_music = QPushButton('↻  Changer de musique')" in source
    assert 'self.change_music.clicked.connect(self._show_import)' in source


def test_file_dialogs_still_use_real_stem_loader():
    source = UI.read_text(encoding='utf-8')
    assert 'pick.clicked.connect(self._choose_files)' in source
    assert 'folder.clicked.connect(self._choose_folder)' in source
    assert 'self.stems.choose_files()' in source
    assert 'self.stems.browse()' in source


def test_successful_new_load_resets_stale_comparison():
    source = UI.read_text(encoding='utf-8')
    segment = source.split('    def _audio_loaded(self, count, label):')[1].split('    def _restore(self):')[0]
    for expected in ['self._close_player()', 'self._report = None', 'self._analysed = False',
                     "self.analysis_line.setText('Analyse en attente…')", 'self._go(0)']:
        assert expected in segment


def test_reimport_blocked_while_processing():
    source = UI.read_text(encoding='utf-8')
    assert 'self._player_busy()' in source.split('    def _can_change_music(self):')[1].split('    def _show_import(self):')[0]
    assert "getattr(self.stems, '_guided_pipeline', False)" in source
