"""Integrated nine-way comparison: three premixes x three *opt-in* Pro-C 3 copies.

Never changes the originals. Only an explicitly heart-approved compression path can be
handed to mastering; A/B/C audition alone is never an approval.
"""
from __future__ import annotations

from pathlib import Path
import json
import hashlib
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QCheckBox, QFrame, QMessageBox
from .waveform_preview import WaveformStrip
from .pro_c3_song_preview import make_preview, audition_files, verify_source, save_choice
from .pro_c3_loudness_match import preview_volume, BASE_VOLUME

MIXES = ('balanced', 'vocal-focus', 'punchy')
COMPRESSIONS = ('original', 'gentle', 'firm')
MIX_NAMES = {'balanced':'Balanced', 'vocal-focus':'Vocal Focus', 'punchy':'Punchy'}
COMP_NAMES = {'original':'Original', 'gentle':'Gentle', 'firm':'Firm'}


def session_fingerprint(paths):
    """Change cache identity if any premix is replaced, edited or moved."""
    entries = []
    for key in MIXES:
        p = Path(paths[key]).resolve()
        stat = p.stat()
        entries.append([key, str(p), stat.st_size, stat.st_mtime_ns])
    return hashlib.sha256(json.dumps(entries, ensure_ascii=False).encode('utf-8')).hexdigest()


def _cache_valid(root, result):
    """Cache only renders created inside the application's own preview directory."""
    if result.get('status') != 'ready' or set(result.get('mixes', {})) != set(MIXES):
        return False
    allowed = (Path(root).resolve() / 'settings' / 'pro_c3_song_previews').resolve()
    for mix in MIXES:
        data = result['mixes'][mix]
        if not data.get('report') or set(data.get('paths', {})) != set(COMPRESSIONS):
            return False
        for comp in COMPRESSIONS:
            path = Path(data['paths'][comp]).resolve()
            if not path.is_file() or path.suffix.lower() != '.wav':return False
            if comp != 'original' and not path.is_relative_to(allowed):return False
    return True


class PrepareNineWorker(QThread):
    completed = Signal(object)

    def __init__(self, root, paths, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.paths = {k: Path(p).resolve() for k, p in paths.items()}

    def run(self):
        try:
            for path in self.paths.values():
                verify_source(path)
            fingerprint = session_fingerprint(self.paths)
            manifest = self.root / 'settings' / 'pro_c3_unified_cache.json'
            if manifest.is_file():
                try:
                    cache = json.loads(manifest.read_text(encoding='utf-8'))
                    if cache.get('fingerprint') == fingerprint and _cache_valid(self.root, cache.get('result', {})):
                        self.completed.emit(dict(cache['result'], cached=True))
                        return
                except (OSError, ValueError, TypeError, KeyError):
                    pass
            data = {}
            for key in MIXES:
                result = make_preview(self.root, self.paths[key])
                if result.get('status') != 'needs_review':
                    raise ValueError(key + ' : ' + str(result.get('error', 'Rendu incomplet')))
                sources = audition_files(self.root, result)
                data[key] = {'paths': {k: str(v) for k, v in sources.items()}, 'report': result}
            payload = {'status':'ready', 'mixes':data}
            # Cache only validated complete result; atomic replace prevents partial JSON.
            if _cache_valid(self.root, payload):
                try:
                    manifest.parent.mkdir(parents=True, exist_ok=True)
                    temp = manifest.with_suffix('.json.tmp')
                    temp.write_text(json.dumps({'fingerprint':fingerprint,'result':payload}, ensure_ascii=False, indent=2), encoding='utf-8')
                    temp.replace(manifest)
                except (OSError, TypeError, ValueError):
                    pass  # Cache failure cannot invalidate successful audio renders.
            self.completed.emit(payload)
        except Exception as exc:
            self.completed.emit({'status':'failed', 'error': f'{type(exc).__name__}: {exc}'})


class UnifiedComparison(QWidget):
    """Inline Qt widget; all nine media clocks run muted except the active one."""
    prepared = Signal(bool)
    mixSelected = Signal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.worker = None
        self._files = {}
        self._reports = {}
        self._sources = {}
        self._loaded = set()
        self._players = {}
        self._outputs = {}
        self._active = ('balanced','original')
        self._approved = None
        self._running = False
        self._started = False
        self._disposed = False
        self._pending_play = False
        self._max_ms = 0
        self._session_tag = None
        self._timer = QTimer(self)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._sync)

        self.setObjectName('unifiedStudio')
        self.setStyleSheet("""QWidget#unifiedStudio {background:#111217;border:1px solid #333542;border-radius:14px;}
            QWidget#unifiedStudio QLabel {background:transparent;border:none;}
            QWidget#unifiedStudio QPushButton {border-radius:9px;min-height:34px;padding:7px 10px;}
            QWidget#unifiedStudio QPushButton:disabled {color:#7c8393;}""")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(13)
        header = QHBoxLayout()
        brand = QLabel('AUTO STUDIO')
        brand.setStyleSheet('font-size:18px;font-weight:750;color:#f5f6fa;')
        header.addWidget(brand)
        header.addStretch()
        ver = QLabel('v0.23.1')
        ver.setStyleSheet('color:#9da4b4;font-size:11px;')
        header.addWidget(ver)
        layout.addLayout(header)
        self.recommendation = QLabel('✦ Hermes : recommandation de mix en attente · Original par défaut (compression non choisie par IA)')
        self.recommendation.setWordWrap(True)
        self.recommendation.setStyleSheet('color:#c7b8ff;font-size:12px;')
        layout.addWidget(self.recommendation)
        section_mix = QLabel('1. Mixage')
        section_mix.setStyleSheet('font-size:14px;font-weight:700;color:#f3f3f7;')
        layout.addWidget(section_mix)
        mix_row = QHBoxLayout()
        self.mix_buttons = {}
        for mix in MIXES:
            button = QPushButton(MIX_NAMES[mix])
            button.setMinimumHeight(48)
            button.clicked.connect(lambda _=False, m=mix: self.mixSelected.emit(m))
            self.mix_buttons[mix] = button
            mix_row.addWidget(button, 1)
        layout.addLayout(mix_row)
        border = QFrame()
        border.setFrameShape(QFrame.HLine)
        border.setStyleSheet('background:#343640;max-height:1px;')
        layout.addWidget(border)
        section_comp = QLabel('2. Compression · Pro-C 3')
        section_comp.setStyleSheet('font-size:14px;font-weight:700;color:#f3f3f7;')
        layout.addWidget(section_comp)
        choices = QHBoxLayout()
        self.buttons = {}
        for comp in COMPRESSIONS:
            button = QPushButton(COMP_NAMES[comp] + ('\nAucune' if comp == 'original' else '\nDouce' if comp == 'gentle' else '\nForte'))
            button.clicked.connect(lambda _=False, c=comp: self.select_compression(c))
            button.setMinimumHeight(54)
            button.setEnabled(comp == 'original')
            self.buttons[comp] = button
            choices.addWidget(button, 1)
        layout.addLayout(choices)
        self.status = QLabel('Les copies Pro-C 3 se préparent automatiquement en entrant dans Comparer. Les originaux ne changent pas.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color:#acb3c3;font-size:11px;')
        layout.addWidget(self.status)
        self.prepare = QPushButton('↻  Régénérer les copies (cache disponible)')
        self.prepare.setObjectName('secondary')
        self.prepare.clicked.connect(self._confirm_prepare)
        self.prepare.setVisible(False)   # Recovery only; no mandatory extra button.
        layout.addWidget(self.prepare)
        player_label = QLabel('Lecteur commun')
        player_label.setStyleSheet('font-size:14px;font-weight:700;color:#f3f3f7;')
        layout.addWidget(player_label)
        self.waveform = WaveformStrip(self)
        self.waveform.setFixedHeight(64)
        self.waveform.setActive(True)
        self.waveform.clickedPosition.connect(self._waveform_seek)
        layout.addWidget(self.waveform)
        transport = QHBoxLayout()
        self.play_button = QPushButton('▶ Écouter')
        self.play_button.clicked.connect(self.toggle)
        self.play_button.setEnabled(False)
        self.stop_button = QPushButton('■ Stop')
        self.stop_button.clicked.connect(self.stop)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setEnabled(False)
        self.seek.sliderReleased.connect(self._seek)
        self.clock = QLabel('00:00 / 00:00')
        for widget in (self.play_button, self.stop_button, self.seek, self.clock):
            transport.addWidget(widget, 1 if widget is self.seek else 0)
        layout.addLayout(transport)
        self.match = QCheckBox('Égaliser le volume à l’écoute (RMS approximatif)')
        self.match.setChecked(True)
        self.match.toggled.connect(self._apply_levels)
        layout.addWidget(self.match)
        hearts = QHBoxLayout()
        love_label = QLabel('Choix pour Mastering :')
        hearts.addWidget(love_label)
        self.hearts = {}
        for comp in COMPRESSIONS:
            button = QPushButton('♡ ' + COMP_NAMES[comp])
            button.setEnabled(False)
            button.clicked.connect(lambda _=False, c=comp: self.approve(c))
            self.hearts[comp] = button
            hearts.addWidget(button, 1)
        layout.addLayout(hearts)
        self.approval_status = QLabel('Aucune compression approuvée. Le prémix original sera utilisé pour le mastering.')
        self.approval_status.setWordWrap(True)
        self.approval_status.setStyleSheet('font-size:11px;color:#afb7c9;')
        layout.addWidget(self.approval_status)
        self._update_styles()

    @property
    def active(self):
        return self._active

    def recommended_mix(self, mix, reference_used=False):
        if mix in MIXES:
            ref = ' · référence prise en compte' if reference_used else ''
            self.recommendation.setText('✦ Hermes recommande : ' + MIX_NAMES[mix] + ' + Original (compression par défaut, PAS un choix IA)' + ref + '.')

    def is_busy(self):
        return bool(self.worker and self.worker.isRunning())

    def prepare_automatically(self):
        """Non-destructive cached renders as the user opens Compare."""
        if self.is_busy() or self._files or len(self._sources) != 3:return
        self._begin_prepare()

    def _begin_prepare(self):
        if self.is_busy() or len(self._sources) != 3:return
        self.stop()
        self._dispose_players()
        self._files.clear()
        self._reports.clear()
        self._approved = None
        self._active = (self._active[0], 'original')
        self._update_styles()
        self._refresh_hearts()
        self._disposed = False
        self.prepare.setEnabled(False)
        self.play_button.setEnabled(False)
        self.seek.setEnabled(False)
        self.status.setText('Préparation des 9 pistes ou récupération du cache… Aucun original modifié.')
        self.worker = PrepareNineWorker(self.root, dict(self._sources), self)
        self.worker.completed.connect(self._on_prepared)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _waveform_seek(self, fraction):
        if not self._players:return
        self.seek.setValue(round(self._max_ms * max(0.0,min(1.0,fraction))))
        self._seek()

    def set_waveform(self, envelope):
        self.waveform.setData(envelope)

    def _confirm_prepare(self):
        if self.is_busy() or len(self._sources) != 3:return
        self._begin_prepare()

    def set_sources(self, paths, session_tag=None):
        if self.is_busy():
            return False
        new = {key: Path(paths[key]).resolve() for key in MIXES if paths.get(key)}
        if len(new) != 3:
            return False
        changed = session_tag != self._session_tag or new != self._sources
        if changed:
            self.reset()
            self._session_tag = session_tag
            self._sources = new
            self.status.setText('Trois prémix disponibles. Prépare six copies pour activer les 9 combinaisons. Aucun master modifié.')
        return changed

    def _on_prepared(self, result):
        self.prepare.setEnabled(True)
        if result.get('status') != 'ready':
            self.status.setText('Rendu impossible : ' + str(result.get('error','erreur inconnue')) + ' · Vérifie le format stéréo WAV 48 kHz.')
            self.prepare.setVisible(True)
            self.prepared.emit(False)
            return
        self._files = {(mix, comp): Path(result['mixes'][mix]['paths'][comp]) for mix in MIXES for comp in COMPRESSIONS}
        self._reports = {mix:result['mixes'][mix]['report'] for mix in MIXES}
        # Only prepare synchronized playback once all nine immutable copies exist.
        self._setup_players()
        self.prepare.setVisible(False)
        self.status.setText(('9 combinaisons récupérées du cache.' if result.get('cached') else '9 combinaisons générées.') + ' Change mix et compression pendant la lecture. ♥ approuve pour le mastering.')
        self.prepared.emit(True)

    def _setup_players(self):
        self._dispose_players()
        self._disposed = False
        for key, path in self._files.items():
            player = QMediaPlayer(self)
            output = QAudioOutput(self)
            output.setMuted(True)
            output.setVolume(BASE_VOLUME)
            player.setAudioOutput(output)
            player.mediaStatusChanged.connect(lambda status, k=key: self._media_loaded(k, status))
            player.positionChanged.connect(lambda pos, k=key: self._position(k, pos))
            player.errorOccurred.connect(lambda *_args, k=key: self._player_error(k))
            self._players[key] = player
            self._outputs[key] = output
        self._loaded.clear()
        self._started = False
        self._running = False
        self._max_ms = min(int(self._reports[k]['source_frames'] * 1000 / 48000) for k in MIXES)
        self.seek.setRange(0, self._max_ms)
        self.seek.setEnabled(True)
        self.play_button.setEnabled(True)
        for comp,button in self.buttons.items():button.setEnabled(True)
        for button in self.hearts.values():button.setEnabled(True)
        for key, path in self._files.items():
            self._players[key].setSource(QUrl.fromLocalFile(str(path)))
        self._apply_levels()
        self._update_styles()

    def _media_loaded(self, key, status):
        if self._disposed or key not in self._players:return
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self._loaded.add(key)
            if len(self._loaded) == 9 and self._pending_play:
                self._pending_play = False
                self._start_all()
        elif status == QMediaPlayer.InvalidMedia:
            self._pending_play = False
            self.status.setText('Erreur de décodage audio : ' + str(key))

    def _player_error(self, key):
        if not self._disposed and key in self._players:
            self.status.setText('Erreur de lecture ' + str(key) + ': ' + self._players[key].errorString())

    def _start_all(self):
        if self._disposed or not self._players:return
        for key, p in self._players.items():
            p.setPosition(min(p.position(), self._max_ms))
            self._outputs[key].setMuted(True)
            p.play()
        self._running = True
        self._started = True
        self._timer.start()
        self._select_audible()
        self.play_button.setText('Ⅱ Pause')

    def _select_audible(self):
        for key, output in self._outputs.items():
            output.setMuted(not self._running or key != self._active)

    def select_mix(self, mix):
        if mix not in MIXES:return
        self._switch((mix, self._active[1]))

    def select_compression(self, comp):
        if comp not in COMPRESSIONS or (comp != 'original' and not self._files):return
        self._switch((self._active[0], comp))

    def _switch(self, key):
        if key == self._active:return
        if self._running and self._active in self._outputs:
            self._outputs[self._active].setMuted(True)
            current = self._players[self._active].position()
            if key in self._players and abs(self._players[key].position()-current) > 65:
                self._players[key].setPosition(current)
        self._active = key
        self._select_audible()
        self._update_styles()
        self._refresh_hearts()
        if key in self._players:self._position(key, self._players[key].position())

    def _update_styles(self):
        for mix, button in self.mix_buttons.items():
            selected = mix == self._active[0]
            button.setStyleSheet('QPushButton {background:#252b3a;border:2px solid #668dd0;color:white;font-weight:700;}' if selected else 'QPushButton {background:#171920;border:1px solid #373c46;color:#c7cbd5;}')
        for comp, button in self.buttons.items():
            selected = comp == self._active[1]
            button.setStyleSheet('QPushButton {background:#29263c;border:2px solid #9285e3;color:white;font-weight:700;}' if selected else 'QPushButton {background:#171920;border:1px solid #373c46;color:#c7cbd5;}')

    def _refresh_hearts(self):
        for comp, button in self.hearts.items():
            selected = self._approved == (self._active[0], comp)
            button.setText(('♥ ' if selected else '♡ ') + COMP_NAMES[comp])
            button.setStyleSheet('QPushButton { color:#F05C8D;font-weight:700; }' if selected else '')

    def approve(self, comp):
        key = (self._active[0], comp)
        if key not in self._files:return
        if comp != 'original':
            if self._reports.get(key[0]) is None:return
            try: save_choice(self.root, self._reports[key[0]], comp)
            except Exception as exc:
                QMessageBox.warning(self, 'Préférence', str(exc));return
        self._approved = key
        self._refresh_hearts()
        self.approval_status.setText('♥ ' + MIX_NAMES[key[0]]+' + '+COMP_NAMES[comp] + ' approuvé pour le prochain Mastering. Choix manuel, pas Hermes.')

    def master_source(self, selected_mix):
        """Never automatically master a compressed version without ♥ explicit approval."""
        if self._approved and self._approved[0] == selected_mix:
            return self._files.get(self._approved)
        return self._sources.get(selected_mix)

    def master_variant(self, selected_mix):
        if self._approved and self._approved[0] == selected_mix:
            return selected_mix + '-' + self._approved[1]
        return selected_mix + '-original'

    def toggle(self):
        if not self._players or self._disposed:return
        if self._running:
            self._running = False
            self._timer.stop()
            for p in self._players.values():p.pause()
            self._select_audible()
            self.play_button.setText('▶ Écouter')
            return
        if len(self._loaded) < 9:
            self._pending_play = True
            self.play_button.setText('Chargement…')
            return
        if self._started:
            current = self._players[self._active].position()
            if current >= self._max_ms - 150:current = 0
            for p in self._players.values():p.setPosition(current)
        self._start_all()

    def stop(self):
        self._pending_play = False
        self._running = False
        self._timer.stop()
        for key, p in self._players.items():
            self._outputs[key].setMuted(True)
            p.stop()
            p.setPosition(0)
        self.play_button.setText('▶ Écouter')
        self.seek.setValue(0)
        self.waveform.setPosition(0)
        self.clock.setText('00:00 / '+f'{self._max_ms//60000:02}:{self._max_ms//1000%60:02}')

    def _seek(self):
        if not self._players:return
        pos = max(0,min(self.seek.value(), self._max_ms))
        for p in self._players.values():p.setPosition(pos)

    def _position(self, key, pos):
        if key != self._active or self._disposed:return
        pos = min(max(int(pos),0),self._max_ms)
        if not self.seek.isSliderDown():self.seek.setValue(pos)
        self.clock.setText(f'{pos//60000:02d}:{pos//1000%60:02d} / {self._max_ms//60000:02d}:{self._max_ms//1000%60:02d}')
        self.waveform.setPosition(pos / max(1,self._max_ms))
        if pos >= self._max_ms and self._running:self.toggle()

    def _sync(self):
        if not self._running or self._disposed:return
        pos = self._players[self._active].position()
        for key, player in self._players.items():
            if key != self._active and abs(player.position()-pos)>80:
                player.setPosition(pos)

    def _apply_levels(self, *_):
        if self._disposed:return
        for key, output in self._outputs.items():
            profile = self._reports.get(key[0], {}).get('playback_matching')
            try:volume=preview_volume(profile, key[1], self.match.isChecked())
            except (ValueError, TypeError, KeyError):volume=BASE_VOLUME
            output.setVolume(volume)

    def _dispose_players(self):
        self._disposed = True
        self._running = False
        self._pending_play = False
        self._timer.stop()
        for output in self._outputs.values():
            output.setMuted(True)
            output.setVolume(0.0)
        for player in self._players.values():
            player.stop()
            player.setSource(QUrl())
            player.setAudioOutput(None)
            player.deleteLater()
        for output in self._outputs.values(): output.deleteLater()
        self._players.clear()
        self._outputs.clear()
        self._loaded.clear()
        self._started = False

    def reset(self):
        self._dispose_players()
        self._files.clear()
        self._reports.clear()
        self._approved = None
        self._session_tag = None
        self._sources = {}
        self._active = ('balanced','original')
        self.waveform.setData(None)
        self.prepare.setVisible(False)
        self.prepare.setEnabled(True)
        self.play_button.setEnabled(False)
        self.seek.setEnabled(False)
        for button in self.hearts.values():button.setEnabled(False)
        for comp,button in self.buttons.items():button.setEnabled(comp == 'original')
        self._refresh_hearts()
        self.approval_status.setText('Aucune compression approuvée pour le mastering. Original utilisé par défaut.')
        self._update_styles()

    def shutdown(self):
        self._dispose_players()

    def closeEvent(self, event):
        if self.is_busy():
            event.ignore()
            QMessageBox.information(self, 'Rendu en cours', 'Attends la fin du rendu JUCE avant de fermer.')
            return
        self.shutdown()
        super().closeEvent(event)
