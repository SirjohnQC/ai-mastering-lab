"""Opt-in GUI for real-mix sandboxed Pro-C 3 previews, never Auto Produce."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt, QUrl, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QFileDialog, QMessageBox, QSlider, QCheckBox)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from .pro_c3_song_preview import make_preview, audition_files, save_choice, verify_source
from .pro_c3_loudness_match import preview_volume, BASE_VOLUME

class RenderWorker(QThread):
    complete = Signal(object)
    def __init__(self, root, path, parent=None):
        super().__init__(parent)
        self.root, self.path = Path(root), Path(path)
    def run(self):
        try:
            result = make_preview(self.root, self.path)
        except Exception as exc:
            result = {'status':'failed', 'error':f'{type(exc).__name__}: {exc}'}
        self.complete.emit(result)

class SafePreviewDialog(QDialog):
    """Keep the native render thread alive; do not close Qt parent mid-render."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy_check = lambda: False
        self.before_close = lambda: None
    def closeEvent(self, event):
        if self.busy_check():
            QMessageBox.information(self, 'Rendu en cours', 'Le rendu JUCE doit se terminer avant de fermer cette fenêtre.')
            event.ignore()
            return
        self.before_close()
        super().closeEvent(event)
    def reject(self):
        if self.busy_check():
            QMessageBox.information(self, 'Rendu en cours', 'Le rendu JUCE doit se terminer avant de fermer cette fenêtre.')
            return
        self.before_close()
        super().reject()

    def done(self, result):
        # Also covers accept(), dialog buttons and programmatic done().
        # The owner separately guarantees teardown when exec() returns.
        if self.busy_check():
            QMessageBox.information(self, 'Rendu en cours', 'Le rendu JUCE doit se terminer avant de fermer cette fenêtre.')
            return
        self.before_close()
        super().done(result)

class SongCompressionPreviewDialog:
    def __init__(self, root, parent=None, *, initial_source=None, studio_context=None):
        self.root = Path(root)
        self.initial_source = Path(initial_source).resolve() if initial_source else None
        self.studio_context = studio_context if isinstance(studio_context, dict) else None
        self.dialog = SafePreviewDialog(parent)
        self.dialog.busy_check = lambda: bool(self.worker and self.worker.isRunning())
        self.dialog.before_close = self._shutdown_audio
        self.dialog.setWindowTitle('Pro-C 3 — A/B/C sur COPIE de mix (expérimental)')
        self.dialog.resize(690, 370)
        layout = QVBoxLayout(self.dialog)
        self.note = QLabel('EXPÉRIMENTAL : sélection volontaire d’un WAV stéréo 48 kHz (2 s à 10 min). '
                           'Original / Gentle / Firm sont des COPIES dans settings/. Aucun master ou stem original modifié. '
                           'Les trois lecteurs jouent en parallèle pour comparer A/B/C sans redémarrer. Auto Produce reste verrouillé.')
        self.note.setWordWrap(True); layout.addWidget(self.note)
        # Informational only: this is the mix recommendation from Auto Studio,
        # NOT a Hermes-derived choice of Pro-C 3 settings.
        if self.studio_context:
            mix = str(self.studio_context.get('selected_mix', '?'))
            ai_pick = str(self.studio_context.get('hermes_mix_choice', '?'))
            if self.studio_context.get('hermes_mode') == 'hermes':
                message = 'Hermes recommande le prémix : ' + ai_pick
                if self.studio_context.get('reference_used'):
                    message += ' (références prises en compte)'
                message += '. Mix ouvert : ' + mix + '.'
            else:
                message = 'Mix ouvert : ' + mix + '. Recommandation Hermes indisponible ou de secours.'
            context_label = QLabel(message + ' Compression Gentle/Firm = presets de laboratoire, PAS des réglages choisis par Hermes.')
            context_label.setWordWrap(True)
            layout.addWidget(context_label)
        choose = QPushButton('Préparer les trois copies du mix sélectionné…' if self.initial_source else 'Choisir un WAV et générer les trois copies…')
        choose.clicked.connect(self.pick_and_render)
        layout.addWidget(choose); self.choose = choose
        self.status = QLabel(('Mix prêt : ' + self.initial_source.name + ' — confirmation requise.') if self.initial_source else 'Aucun mix sélectionné.'); self.status.setWordWrap(True); layout.addWidget(self.status)
        # Dedicated players for synchronized comparisons. Qt setSource() is disruptive;
        # never change source while switching A/B/C during playback.
        self.players = {}
        self.outputs = {}
        self.loaded = set()
        self._session_generation = 0
        self._started = False
        self._start_requested = False
        self._prepare_position = 0
        self._transport_running = False
        self._sync_timer = QTimer(self.dialog)
        self._sync_timer.setInterval(800)
        self._sync_timer.timeout.connect(self._sync_players)
        for key in ('original', 'gentle', 'firm'):
            player = QMediaPlayer(self.dialog)
            output = QAudioOutput(self.dialog)
            output.setVolume(BASE_VOLUME)
            output.setMuted(True)
            player.setAudioOutput(output)
            player.mediaStatusChanged.connect(lambda status, k=key: self._loaded(k, status))
            player.positionChanged.connect(lambda position, k=key: self._position(k, position))
            player.errorOccurred.connect(lambda *args, k=key: self._playback_error(k))
            self.players[key] = player
            self.outputs[key] = output
        self.sources = {}; self.report = None; self.kind = 'original'
        self.playback_matching = None
        self.selected_preference = None
        self._is_closing = False
        self._audio_disposed = False
        self.worker = None
        buttons = QHBoxLayout()
        self.switch_buttons = {}
        for key, name in (('original','A · Original'),('gentle','B · Gentle'),('firm','C · Firm')):
            b = QPushButton(name); b.setEnabled(False)
            b.clicked.connect(lambda checked=False, k=key: self.switch(k))
            self.switch_buttons[key] = b; buttons.addWidget(b)
        layout.addLayout(buttons)
        transport = QHBoxLayout()
        self.play_btn = QPushButton('▶ Écouter'); self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.toggle); transport.addWidget(self.play_btn)
        stop = QPushButton('■ Stop'); stop.clicked.connect(self.stop); transport.addWidget(stop)
        self.seek = QSlider(Qt.Horizontal); self.seek.setEnabled(False)
        self.seek.setRange(0,1000); self.seek.sliderReleased.connect(self._seek_all)
        transport.addWidget(self.seek,1)
        self.clock = QLabel('00:00 / 00:00'); transport.addWidget(self.clock)
        layout.addLayout(transport)
        level_row = QHBoxLayout()
        self.match_checkbox = QCheckBox('Égaliser le volume d’écoute (RMS approximatif)')
        self.match_checkbox.setChecked(True)
        self.match_checkbox.setEnabled(False)
        self.match_checkbox.toggled.connect(self._apply_playback_level)
        level_row.addWidget(self.match_checkbox)
        self.level_status = QLabel('Volumes : non analysés')
        self.level_status.setWordWrap(True)
        level_row.addWidget(self.level_status, 1)
        layout.addLayout(level_row)
        likes = QHBoxLayout(); likes.addWidget(QLabel('Choix manuel (pas Hermes) :'))
        self.heart_buttons = []
        for key in ('original','gentle','firm'):
            b = QPushButton('♡ '+key.title()); b.setEnabled(False)
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False,k=key:self.choose_preference(k))
            self.heart_buttons.append(b); likes.addWidget(b)
        layout.addLayout(likes)
        self.dialog.finished.connect(lambda *_: self._shutdown_audio())

    def pick_and_render(self):
        if self.worker and self.worker.isRunning(): return
        if self.initial_source is not None:
            # Studio handoff: use exactly the mix the user chose in Compare.
            # Never launch a file chooser that could silently switch songs.
            filename = str(self.initial_source)
        else:
            filename, _ = QFileDialog.getOpenFileName(self.dialog,'Sélectionne un mix WAV à prévisualiser', '', 'WAV Audio (*.wav)')
        if not filename: return
        try: verify_source(filename)
        except Exception as exc:
            QMessageBox.warning(self.dialog,'Format non pris en charge',str(exc)); return
        confirmation = QMessageBox.question(self.dialog, 'Créer des copies de test?',
            'Mix : ' + Path(filename).name + '\n\nExécuter Pro-C 3 sur DEUX COPIES de ce WAV et garder une copie originale pour A/B/C ?\n\n'
            'Les résultats restent dans settings/pro_c3_song_previews/. Aucun traitement appliqué au morceau source. '
            'Ces presets de laboratoire ne sont pas des recommandations Hermes.',
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if confirmation != QMessageBox.Yes:return
        self.stop(); self.sources = {}; self.report = None
        self.playback_matching = None
        self.match_checkbox.setEnabled(False)
        self.level_status.setText('Volumes : non analysés')
        self.selected_preference = None
        self._update_hearts()
        self.choose.setEnabled(False)
        for b in [*self.switch_buttons.values(),*self.heart_buttons,self.play_btn]:b.setEnabled(False)
        self.seek.setEnabled(False)
        self.status.setText('JUCE prépare les copies en arrière-plan… (aucun traitement du fichier source)')
        self.worker = RenderWorker(self.root,filename,self.dialog)
        self.worker.complete.connect(self._done)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _done(self, result):
        self.choose.setEnabled(True)
        if result.get('status') != 'needs_review':
            self.status.setText('Prévisualisation refusée : '+result.get('error','Rendu incomplet.'))
            return
        try:
            self.sources = audition_files(self.root,result)
            self.report = result
            self.playback_matching = result.get('playback_matching')
            match_status = (self.playback_matching or {}).get('status')
            self.match_checkbox.setEnabled(match_status in ('ready', 'limited'))
            if self.match_checkbox.isEnabled():
                gains = self.playback_matching['gain_db']
                self.level_status.setText('Gain écoute A / B / C : '
                                          + ' / '.join(f'{gains[k]:+.1f} dB' for k in ('original','gentle','firm'))
                                          + (' · limité à −18 dB' if match_status == 'limited' else ''))
            else:
                self.level_status.setText('Égalisation indisponible; écoute sans correction. ' +
                                          str((self.playback_matching or {}).get('error','')))
            self.max_ms = int(result['source_frames']*1000/48000)
            self.seek.setRange(0,self.max_ms)
            self.seek.setEnabled(True)
            for b in [*self.switch_buttons.values(),*self.heart_buttons,self.play_btn]: b.setEnabled(True)
            self.kind = 'original'
            self._prepare_sources()
            self.status.setText('Trois COPIES prêtes — traitement expérimental. A/B/C conserve la lecture.')
        except Exception as exc:
            self.status.setText('Impossible de charger les copies : '+str(exc))

    def _prepare_sources(self, *, start_when_ready=False, position=0):
        """Load all three sources once, allowing instant switches during playback."""
        self._session_generation += 1
        self.loaded.clear()
        self._started = False
        self._start_requested = bool(start_when_ready)
        self._prepare_position = max(0, min(int(position), max(0, self.max_ms - 1)))
        for key, player in self.players.items():
            self.outputs[key].setMuted(True)
            player.stop()
            player.setSource(QUrl())
        # Source callbacks may be asynchronous. Never autoplay before all are ready.
        for key in ('original', 'gentle', 'firm'):
            self.players[key].setSource(QUrl.fromLocalFile(str(self.sources[key])))
        self._apply_playback_level()
        self._update_switch_styles()

    def _loaded(self, key, status):
        if self._is_closing or not self.sources: return
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self.loaded.add(key)
        elif status == QMediaPlayer.InvalidMedia:
            self.loaded.discard(key)
            self.status.setText('WAV illisible : ' + key + ' — ' + self.players[key].errorString())
            self._start_requested = False
            return
        if len(self.loaded) == 3 and self._start_requested and not self._started:
            self._begin_playback()

    def _begin_playback(self):
        if self._is_closing or len(self.loaded) != 3 or self._started: return
        self._started = True
        self._start_requested = False
        # One clock-position for all streams. Start each player while muted, then
        # expose only the selected stream. Switching never reloads a WAV.
        for key, player in self.players.items():
            player.setPosition(self._prepare_position)
            self.outputs[key].setMuted(True)
            player.play()
        self._transport_running = True
        self._sync_timer.start()
        self._apply_playback_level()
        self._select_audible()
        self.play_btn.setText('Ⅱ Pause')

    def _select_audible(self):
        for key, output in self.outputs.items():
            # Mute secondary streams, but keep their playback clocks advancing.
            output.setMuted(self._is_closing or not self._transport_running or key != self.kind)

    def _update_switch_styles(self):
        for key, button in self.switch_buttons.items():
            button.setStyleSheet('font-weight:700;' if key == self.kind else '')

    def switch(self, kind):
        if self._is_closing or kind not in self.sources:return
        if kind == self.kind: return
        was_playing = self._transport_running
        old = self.kind
        if was_playing:
            # Muting first prevents simultaneous audible streams during change.
            self.outputs[old].setMuted(True)
            pos = self.players[old].position()
            next_pos = self.players[kind].position()
            if abs(pos - next_pos) > 65:
                self.players[kind].setPosition(pos)
        self.kind = kind
        self._apply_playback_level()
        self._select_audible()
        self._update_switch_styles()
        self._position(kind, self.players[kind].position())

    def _apply_playback_level(self, *_):
        """Set individual listening gains only; never alter audio files."""
        if self._is_closing: return
        enabled = self.match_checkbox.isChecked() and self.match_checkbox.isEnabled()
        for key, output in self.outputs.items():
            try:
                volume = preview_volume(self.playback_matching, key, enabled)
            except (ValueError, KeyError, TypeError):
                volume = BASE_VOLUME
            output.setVolume(volume)

    def _playback_error(self, key):
        if self._is_closing: return
        self.status.setText('Erreur de lecture ' + key + ' : ' + self.players[key].errorString())

    def _position(self, key, pos):
        if not self.report or self._is_closing or key != self.kind:return
        pos = max(0,min(int(pos),self.max_ms))
        if not self.seek.isSliderDown():self.seek.setValue(pos)
        self.clock.setText(f'{pos//60000:02d}:{(pos//1000)%60:02d} / {self.max_ms//60000:02d}:{(self.max_ms//1000)%60:02d}')
        if pos >= self.max_ms and self._transport_running:
            self._pause_all()

    def _seek_all(self):
        if not self.sources or self._is_closing: return
        pos = min(max(0, int(self.seek.value())), self.max_ms)
        self._prepare_position = pos
        for player in self.players.values():
            if not player.source().isEmpty(): player.setPosition(pos)
        self._position(self.kind, pos)

    def _sync_players(self):
        """Correct large backend clock drift; never seek on every frame."""
        if not self._transport_running or self._is_closing:return
        reference = self.players[self.kind].position()
        for key, player in self.players.items():
            if key != self.kind and abs(player.position() - reference) > 80:
                player.setPosition(reference)

    def _pause_all(self):
        self._transport_running = False
        self._sync_timer.stop()
        for player in self.players.values(): player.pause()
        self._select_audible()
        self.play_btn.setText('▶ Écouter')

    def toggle(self):
        if self._is_closing or not self.sources:return
        if self._transport_running:
            self._pause_all()
            return
        if self._started and all(not p.source().isEmpty() for p in self.players.values()):
            if self.players[self.kind].position() >= self.max_ms - 150:
                for player in self.players.values():player.setPosition(0)
            reference = self.players[self.kind].position()
            for player in self.players.values():
                if abs(player.position() - reference) > 65:player.setPosition(reference)
                player.play()
            self._transport_running = True
            self._sync_timer.start()
            self._apply_playback_level()
            self._select_audible()
            self.play_btn.setText('Ⅱ Pause')
            return
        if len(self.loaded) == 3:
            self._begin_playback()
        else:
            self._prepare_sources(start_when_ready=True, position=self._prepare_position)
            self.play_btn.setText('Chargement…')

    def stop(self):
        """Hard stop: silence all three outputs and release backend file sources."""
        self._transport_running = False
        self._start_requested = False
        self._started = False
        self._sync_timer.stop()
        for key, player in self.players.items():
            self.outputs[key].setMuted(True)
            player.stop()
            player.setSource(QUrl())
        self.loaded.clear()
        self._prepare_position = 0
        self.seek.setValue(0)
        if self.report:
            self.clock.setText(f'00:00 / {self.max_ms//60000:02d}:{(self.max_ms//1000)%60:02d}')
        self.play_btn.setText('▶ Écouter')

    def _shutdown_audio(self):
        """Permanently dispose ALL three Qt playback backends on dialog exit.

        Stop alone is insufficient: QDialog may remain allocated after exec(),
        leaving QAudioOutput/Windows multimedia backends active in the background.
        This teardown is idempotent because closeEvent, done(), finished and the
        owner can all independently request cleanup.
        """
        if self._audio_disposed:
            return
        self._audio_disposed = True
        self._is_closing = True
        self._transport_running = False
        self._start_requested = False
        self._started = False
        self._sync_timer.stop()
        # Kill callbacks before destroying media backends. Muting must happen
        # BEFORE stop/detach, so even a delayed backend stop cannot be audible.
        for key in ('original', 'gentle', 'firm'):
            output = self.outputs.get(key)
            if output is not None:
                output.setMuted(True)
                output.setVolume(0.0)
        for key in ('original', 'gentle', 'firm'):
            player = self.players.get(key)
            if player is None:
                continue
            try:
                player.stop()
                player.setSource(QUrl())
                player.setAudioOutput(None)
            finally:
                player.deleteLater()
        for output in self.outputs.values():
            output.deleteLater()
        self.loaded.clear()
        self.sources = {}
        self.players.clear()
        self.outputs.clear()
        self.play_btn.setText('▶ Écouter')

    def _update_hearts(self):
        for kind, button in zip(('original','gentle','firm'), self.heart_buttons):
            chosen = kind == self.selected_preference
            button.setChecked(chosen)
            button.setText(('♥ ' if chosen else '♡ ') + kind.title())
            button.setStyleSheet('QPushButton { color: #F05C8D; font-weight: 700; }' if chosen else '')

    def choose_preference(self,kind):
        if not self.report:return
        try:save_choice(self.root,self.report,kind)
        except Exception as exc:
            QMessageBox.warning(self.dialog,'Choix non sauvegardé',str(exc));return
        self.selected_preference = kind
        self._update_hearts()
        self.status.setText('♥ Choix '+kind.title()+' enregistré pour ce test. Hermes ne l’utilise pas.')

    def exec(self):
        # Both menu entry points use this wrapper: closing by X, Escape,
        # accept/reject, parent shutdown or an exception cannot leave streams.
        try:
            return self.dialog.exec()
        finally:
            self._shutdown_audio()
            self.dialog.deleteLater()
