"""Optional non-destructive A/B playback of an EQ audition.

Own QMediaPlayer is never used to master or replace source. Always stop other
players before starting playback from the calling page.
"""
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from .waveform_preview import WaveformStrip, WaveformLoader


class AIFXABPlayer(QFrame):
    def __init__(self, parent=None, on_play=None):
        super().__init__(parent)
        self.on_play = on_play
        self.sources = {}
        self._kind = 'before'
        self._token = 0
        self._loaders = []
        self._seek_dragging = False
        self._volumes = {'before': .65, 'after': .65}
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.output.setVolume(.65)
        self.player.setAudioOutput(self.output)
        self.setStyleSheet('QFrame {background:#17181f;border:1px solid #35394a;border-radius:9px;} QLabel {border:none;background:transparent;}')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(8)
        top = QHBoxLayout()
        self.before_button = QPushButton('A · Avant (original)')
        self.after_button = QPushButton('B · Après (Pro-Q 4)')
        self.before_button.clicked.connect(lambda: self.switch('before'))
        self.after_button.clicked.connect(lambda: self.switch('after'))
        top.addWidget(self.before_button)
        top.addWidget(self.after_button)
        layout.addLayout(top)
        self.waveform = WaveformStrip(self)
        self.waveform.clickedPosition.connect(self.seek_fraction)
        layout.addWidget(self.waveform)
        controls = QHBoxLayout()
        self.play_button = QPushButton('▶  Écouter')
        self.play_button.clicked.connect(self.toggle)
        self.stop_button = QPushButton('■  Stop')
        self.stop_button.clicked.connect(self.stop)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.sliderPressed.connect(lambda: setattr(self, '_seek_dragging', True))
        self.seek.sliderReleased.connect(self._seek_released)
        self.clock = QLabel('00:00 / 00:00')
        controls.addWidget(self.play_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.seek, 1)
        controls.addWidget(self.clock)
        layout.addLayout(controls)
        self.note = QLabel('Niveaux RMS approximativement égalisés; compare à l’oreille. Aucun master modifié.')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.player.positionChanged.connect(self._position)
        self.player.durationChanged.connect(lambda *_: self._position(self.player.position()))
        self.player.playbackStateChanged.connect(self._state)
        self.player.errorOccurred.connect(self._error)
        self.player.mediaStatusChanged.connect(self._finish_pending_seek)
        self.hide()

    @staticmethod
    def clock_text(ms):
        s = max(0, int(ms) // 1000)
        return f'{s//60:02d}:{s%60:02d}'

    def load(self, before, after):
        before, after = Path(before).resolve(), Path(after).resolve()
        if not before.is_file() or not after.is_file():
            raise FileNotFoundError('Les deux WAV Avant / Après doivent exister.')
        import soundfile as sf
        a, b = sf.info(str(before)), sf.info(str(after))
        if (a.channels, a.frames, a.samplerate) != (b.channels, b.frames, b.samplerate):
            raise ValueError('Essai EQ non synchronisé : durée, canaux ou fréquence différents.')
        self.reset()
        self.sources = {'before':str(before), 'after':str(after)}
        self._kind = 'before'
        self._volumes = self._matching_volumes(before, after)
        self.output.setVolume(self._volumes['before'])
        self.player.setSource(QUrl.fromLocalFile(str(before)))
        self._refresh_buttons()
        self.show()
        self._token += 1
        token = str(self._token)
        worker = WaveformLoader(token, self.sources, self)
        self._loaders.append(worker)
        worker.generated.connect(lambda t,k,data: self._waveform_done(t,k,data))
        worker.finished.connect(lambda w=worker: self._cleanup_loader(w))
        worker.start()

    @staticmethod
    def _matching_volumes(before, after):
        """Conservative RMS matching over samples; attenuate only the louder side."""
        import math
        import soundfile as sf
        def rms(path):
            squares = 0.0
            count = 0
            with sf.SoundFile(str(path)) as audio:
                # At most first 60 seconds; no need to allocate a whole song.
                limit = min(len(audio), audio.samplerate * 60)
                for chunk in audio.blocks(blocksize=16384, frames=limit, dtype='float32', always_2d=True):
                    import numpy as np
                    squares += float(np.sum(chunk.astype('float64')**2))
                    count += chunk.size
            return math.sqrt(squares / max(1, count))
        try:
            a, b = rms(before), rms(after)
            if min(a,b) <= 1e-9:
                return {'before': .65, 'after': .65}
            quieter = min(a,b)
            return {'before': .65 * min(1., quieter/a), 'after': .65 * min(1., quieter/b)}
        except Exception:
            return {'before': .65, 'after': .65}

    def _cleanup_loader(self, worker):
        if worker in self._loaders:
            self._loaders.remove(worker)
        worker.deleteLater()

    def _waveform_done(self, token, kind, data):
        if token != str(self._token):
            return
        if not hasattr(self, '_envelopes'):
            self._envelopes = {}
        self._envelopes[kind] = data
        if kind == self._kind:
            self.waveform.setData(data)

    def _refresh_buttons(self):
        self.before_button.setEnabled(self._kind != 'before')
        self.after_button.setEnabled(self._kind != 'after')
        self.waveform.setActive(True)

    def switch(self, kind):
        if kind not in self.sources or kind == self._kind:
            return
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        position = self.player.position()
        self.player.stop()
        self._kind = kind
        self.output.setVolume(self._volumes.get(kind, .65))
        self.player.setSource(QUrl.fromLocalFile(self.sources[kind]))
        self.waveform.setData(getattr(self, '_envelopes', {}).get(kind))
        self._refresh_buttons()
        # Some Qt multimedia backends don't allow seeking until media is loaded.
        self._pending_seek = (position, playing)
        self._finish_pending_seek()

    def _finish_pending_seek(self, *_):
        pending = getattr(self, '_pending_seek', None)
        if pending is None or self.player.mediaStatus() not in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            return
        self._pending_seek = None
        position, playing = pending
        self.player.setPosition(position)
        if playing:
            if self.on_play:
                self.on_play()
            self.player.play()

    def toggle(self):
        if not self.sources:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            if self.on_play:
                self.on_play()
            self.player.play()

    def stop(self):
        self.player.stop()
        self.player.setPosition(0)

    def _state(self, state):
        self.play_button.setText('Ⅱ  Pause' if state == QMediaPlayer.PlayingState else '▶  Écouter')

    def _position(self, position):
        duration = self.player.duration()
        fraction = position / duration if duration > 0 else 0
        if not self._seek_dragging:
            self.seek.setValue(round(fraction*1000))
            self.waveform.setPosition(fraction)
        self.clock.setText(f'{self.clock_text(position)} / {self.clock_text(duration)}')

    def _seek_released(self):
        self._seek_dragging = False
        self.seek_fraction(self.seek.value()/1000)

    def seek_fraction(self, fraction):
        if self.sources and self.player.duration() > 0:
            self.player.setPosition(round(max(0., min(1., fraction))*self.player.duration()))

    def _error(self, error, message):
        if error:
            self.note.setText(f'Erreur du lecteur audio : {message}')

    def reset(self):
        self._token += 1
        self.player.stop()
        self.player.setSource(QUrl())
        self.sources = {}
        self._envelopes = {}
        self._pending_seek = None
        self.waveform.setData(None)
        self.clock.setText('00:00 / 00:00')
        self.hide()

    def shutdown(self):
        self.reset()
        for worker in list(self._loaders):
            worker.requestInterruption()
            worker.wait(5000)
