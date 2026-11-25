from pathlib import Path
import ast
SOURCE = Path(__file__).resolve().parents[1] / 'src' / 'mastering_lab'

def test_syntax():
    ast.parse((SOURCE / 'auto_studio_ui.py').read_text(encoding='utf8'))

def test_layout_is_centered_and_limited():
    source = (SOURCE / 'auto_studio_ui.py').read_text(encoding='utf8')
    assert 'self.content.setMaximumWidth(900)' in source
    assert 'outer.addStretch(1)' in source
    assert 'root = QVBoxLayout(self.content)' in source

def test_cards_have_transparent_labels_and_tight_layout():
    source = (SOURCE / 'auto_studio_ui.py').read_text(encoding='utf8')
    assert 'background:transparent;border:none;' in source
    assert 'self.setMaximumHeight(96)' in source
    assert 'self.subtitle = QLabel(subtitle)' in source
    assert 'self.lufs = QLabel' in source
