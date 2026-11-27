"""Exercise the native UI without devices, user settings, plugins or user audio."""
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtSvg import QSvgRenderer

from mastering_lab.desktop import MainWindow
from mastering_lab.studio_brand import ASSETS, studio_icon
from mastering_lab.ui_language import tr


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    with patch('mastering_lab.stem_plus_ui.StemPlusPage._restore_previous_selection'), \
         patch('mastering_lab.auto_studio_ui.AutoStudioPage._restore'), \
         patch('mastering_lab.auto_studio_ui.set_language'):
        win = MainWindow(tmp_path)
        win.show()
        app.processEvents()
        yield win
        win.close()
        app.processEvents()


def test_empty_session_and_language_switch(window):
    page = window.auto_studio
    assert not page.produce_btn.isEnabled()
    for lang in ('fr', 'en'):
        page.language_combo.setCurrentIndex(0 if lang == 'fr' else 1)
        assert page.next_step.text() == tr(lang, 'workflow_import')
        assert page.nav[0].text() == '01  ' + tr(lang, 'import')
        assert [button.isChecked() for button in page.nav] == [True, False, False, False]
        assert page.song_title_import.accessibleName() == tr(lang, 'song_title')
    assert 'Album Mode' in page.import_explanation.text()


def test_loading_real_synthetic_stem_enables_next_action(window, tmp_path):
    from mastering_lab.stem_selection import selection_config
    source = tmp_path / 'vocal.wav'
    sf.write(source, np.zeros((4800, 2), dtype=np.float32), 48000)
    original = source.read_bytes()
    window.stem_plus._load_config(selection_config([source]))
    page = window.auto_studio
    assert page.produce_btn.isEnabled()
    assert page.next_step.text() == tr(page._language, 'workflow_ready')
    assert page.stem_list_scroll.isVisible()
    assert source.read_bytes() == original


def test_compare_cannot_leave_active_production(window):
    page = window.auto_studio
    page._go(1)
    with patch('mastering_lab.auto_studio_ui.QMessageBox.information') as message:
        page.nav[2].click()
    assert message.called
    assert page.stack.currentIndex() == 1
    assert [button.isChecked() for button in page.nav] == [False, True, False, False]


def test_master_navigation_does_not_start_processing(window):
    page = window.auto_studio
    with patch.object(page, '_start_master') as render:
        page.nav[3].click()
        QApplication.processEvents()
    render.assert_not_called()
    assert page.stack.currentIndex() == 3
    assert isinstance(page.stack.widget(3), QScrollArea)
    assert page.next_step.text() == tr(page._language, 'workflow_master')


def test_album_and_return_have_correct_navigation(window):
    page = window.auto_studio
    page.album_header_button.click()
    QApplication.processEvents()
    assert page.stack.currentWidget() is page._album_page
    window.resize(1140, 760)
    QApplication.processEvents()
    assert window.height() <= 800
    assert page.next_step.text() == tr(page._language, 'workflow_album')
    assert not any(button.isChecked() for button in page.nav)
    page.nav[0].click()
    assert page.stack.currentIndex() == 0
    assert page.nav[0].isChecked()


def test_brand_and_laptop_layout(window):
    assert QSvgRenderer(str(ASSETS / 'frankenstem-icon.svg')).isValid()
    assert not studio_icon().pixmap(32, 32).isNull()
    window.resize(1140, 760)
    QApplication.processEvents()
    assert window.height() <= 800
    page = window.auto_studio
    assert page.produce_btn.isVisible()
    assert page.produce_btn.mapTo(window, page.produce_btn.rect().bottomRight()).y() < window.height()
    assert window.stem_plus.findChildren(QScrollArea)
