"""Small shared brand assets for the native studio; no audio dependencies."""
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtSvgWidgets import QSvgWidget


ASSETS = Path(__file__).with_name('assets')


def studio_icon() -> QIcon:
    return QIcon(str(ASSETS / 'frankenstem-icon.svg'))


def brand_mark(parent=None, size=48) -> QSvgWidget:
    mark = QSvgWidget(str(ASSETS / 'frankenstem-icon.svg'), parent)
    mark.setFixedSize(size, size)
    mark.setAccessibleName('FRANKENSTEM')
    return mark
