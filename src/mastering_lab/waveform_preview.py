"""Lightweight, non-destructive min/max waveform previews for Auto Studio.

Every mix uses fixed full-scale amplitude (-1..1) so the three displays are
comparable. Compute asynchronously; never normalize each preview independently.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


def waveform_envelope(path, max_points=1100, cancelled=None):
    """Return (N, 2) min/max amplitudes, preserving peaks over entire recording."""
    path = Path(path)
    with sf.SoundFile(str(path)) as audio:
        length = len(audio)
        if length <= 0:
            return np.empty((0, 2), dtype=np.float32)
        # Using a fixed number of groups bounds memory independently of WAV size.
        bin_size = max(1, int(np.ceil(length / max_points)))
        mins, maxs = [], []
        # Read a bin at a time; the C-backed audio decoder does the heavy lifting.
        while True:
            if cancelled is not None and cancelled():
                return None
            data = audio.read(frames=bin_size, dtype='float32', always_2d=True)
            if not len(data):
                break
            mono_min = float(np.min(data))
            mono_max = float(np.max(data))
            mins.append(max(-1.0, min(1.0, mono_min)))
            maxs.append(max(-1.0, min(1.0, mono_max)))
        return np.stack((mins, maxs), axis=1).astype(np.float32)


class WaveformLoader(QThread):
    generated = Signal(str, str, object)  # session token, mix key, numpy envelope
    failed = Signal(str, str, str)

    def __init__(self, token, paths, parent=None):
        super().__init__(parent)
        self.token = str(token)
        self.paths = dict(paths)

    def run(self):
        for key, path in self.paths.items():
            if self.isInterruptionRequested():
                return
            try:
                env = waveform_envelope(path, cancelled=self.isInterruptionRequested)
                if env is None or self.isInterruptionRequested():
                    return
                self.generated.emit(self.token, key, env)
            except Exception as exc:
                self.failed.emit(self.token, key, str(exc))


class WaveformStrip(QWidget):
    clickedPosition = Signal(float)
    markerClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = None
        self._position = 0.0
        self._active = False
        self._markers = []
        self.setFixedHeight(38)
        self.setMinimumWidth(120)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Clique pour écouter ce passage dans les trois mixages')

    def setData(self, envelope):
        self._data = envelope
        self.update()

    def setMarkers(self, markers):
        """Draw bounded listening markers on the shared waveform itself."""
        self._markers = [float(v) for v in markers
                         if isinstance(v, (int, float)) and
                         not isinstance(v, bool) and 0.0 <= float(v) <= 1.0]
        self.update()

    def setPosition(self, fraction):
        fraction = max(0.0, min(1.0, float(fraction)))
        if abs(fraction - self._position) >= 0.0005:
            self._position = fraction
            self.update()

    def setActive(self, active):
        self._active = bool(active)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        bounds = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(bounds, QColor('#10121a'))
        center = bounds.center().y()
        painter.setPen(QPen(QColor('#313747'), 1))
        painter.drawLine(bounds.left(), center, bounds.right(), center)
        data = self._data
        if data is not None and len(data):
            count = len(data)
            width = max(1, bounds.width())
            height = max(1, bounds.height() - 3)
            pen = QPen(QColor('#a6a9ff' if self._active else '#68758d'), 1)
            painter.setPen(pen)
            for x in range(width):
                a = int(x * count / width)
                b = max(a + 1, int((x + 1) * count / width))
                b = min(b, count)
                lo = float(np.min(data[a:b, 0]))
                hi = float(np.max(data[a:b, 1]))
                top = center - hi * height * 0.48
                bottom = center - lo * height * 0.48
                painter.drawLine(bounds.left() + x, round(top), bounds.left() + x, round(bottom))
        else:
            painter.setPen(QColor('#68758d'))
            painter.drawText(bounds, Qt.AlignCenter, 'Chargement de la forme d’onde…')
        # Highlight review positions above the waveform; pink markers are
        # visually distinct from the lavender transport playhead.
        for index, fraction in enumerate(self._markers):
            mx = bounds.left() + round(fraction * bounds.width())
            painter.setPen(QPen(QColor('#fa81bb'), 2))
            painter.drawLine(mx, bounds.top() + 1, mx, bounds.bottom())
            painter.fillRect(mx - 4, bounds.top() + 1, 9, 5, QColor('#fa81bb'))
        painter.setPen(QPen(QColor('#dfd2ff'), 2))
        px = bounds.left() + round(self._position * bounds.width())
        painter.drawLine(px, bounds.top(), px, bounds.bottom())
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            bounds = self.rect().adjusted(1, 1, -1, -1)
            # A click close to a marker previews the same exact moment as its
            # timestamp button. Else preserve the existing waveform-seek action.
            for index, fraction in enumerate(self._markers):
                marker_x = bounds.left() + fraction * bounds.width()
                if abs(event.position().x() - marker_x) <= 7:
                    self.markerClicked.emit(index)
                    event.accept()
                    return
            frac = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            self.clickedPosition.emit(frac)
            event.accept()
            return
        super().mousePressEvent(event)
