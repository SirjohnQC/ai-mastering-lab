"""Small shared brand assets for the native studio; no audio dependencies."""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from .version import APP_VERSION


ASSETS = Path(__file__).with_name('assets')


def studio_icon() -> QIcon:
    return QIcon(str(ASSETS / 'frankenstem-icon.svg'))


def loading_card() -> QPixmap:
    """Startup identity with space below for live initialization messages."""
    art = QPixmap(570, 230)
    art.fill(QColor('#11151f'))
    painter = QPainter(art)
    renderer = QSvgRenderer(str(ASSETS / 'frankenstem-wordmark.svg'))
    renderer.render(painter, QRectF(20, 18, 530, 132.5))
    painter.setPen(QColor('#a8b6cb'))
    painter.drawText(QRectF(20, 155, 530, 25), Qt.AlignCenter, f'v{APP_VERSION}')
    painter.end()
    return art
