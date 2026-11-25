"""User-approved A/B/C audition of synthetic Pro-C 3 diagnostics only.

Never accepts arbitrary audio paths, edits originals or enables song compression.
"""
from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

KINDS = ('original', 'gentle', 'firm')
LABELS = {'original':'A · Original', 'gentle':'B · Gentle', 'firm':'C · Firm'}


def audition_sources(root: Path) -> tuple[dict[str, Path], dict]:
    """Return only a complete recent synthetic validation session, no song paths."""
    root = Path(root).resolve()
    base = root / 'settings' / 'pro_c3_parameter_validation'
    reports = sorted(base.glob('*/report.json'), reverse=True) if base.is_dir() else []
    if not reports:
        raise FileNotFoundError('Aucun test de paramètres disponible. Lance la validation Pro-C 3.')
    report_path = reports[0].resolve()
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report.get('kind') != 'pro_c3_parameter_validation' or report.get('status') != 'needs_review':
        raise ValueError('Le dernier rapport n’est pas un test de paramètres exploitable.')
    if report.get('automatic_compression_enabled') is not False or report.get('ready_to_render') is not False:
        raise ValueError('Rapport incompatible avec le mode laboratoire verrouillé.')
    scenarios = report.get('scenarios', {})
    if set(scenarios) != {'gentle', 'firm'} or not report.get('comparison', {}).get('firm_more_compression_observed'):
        raise ValueError('Le test synthétique n’a pas confirmé les deux rendus.')
    folder = report_path.parent
    mapping = {'original':folder / 'synthetic-before.wav'}
    for kind in ('gentle', 'firm'):
        data = scenarios[kind]
        if not data.get('parameters') or not data.get('measurements', {}).get('nonzero_output'):
            raise ValueError(f'Mesures {kind} insuffisantes pour une écoute.')
        expected_path = folder / f'synthetic-{kind}-pro-c3.wav'
        recorded_path = Path(data['output_path']).resolve()
        if recorded_path != expected_path.resolve():
            raise ValueError(f'Chemin {kind} inattendu : refus de charger un fichier externe.')
        mapping[kind] = expected_path
    for kind, path in mapping.items():
        if not path.is_file() or not path.resolve().is_relative_to(folder):
            raise FileNotFoundError(f'WAV synthétique {kind} manquant.')
    import soundfile as sf
    infos = {k:sf.info(str(p)) for k,p in mapping.items()}
    a = infos['original']
    if (a.frames, a.channels, a.samplerate) != (192000, 2, 48000):
        raise ValueError('WAV source synthétique inattendu.')
    for kind in ('gentle','firm'):
        b = infos[kind]
        declared = int(scenarios[kind].get('declared_tail_samples', -1))
        if b.channels != a.channels or b.samplerate != a.samplerate or b.frames != a.frames + declared or not (0 <= declared <= 48000):
            raise ValueError(f'Dimensions WAV {kind} incompatibles avec le test.')
    return mapping, report


def store_preference(root: Path, report: dict, selected: str) -> Path:
    """Explicitly record a synthetic listening preference, NOT Hermes training."""
    if selected not in KINDS:
        raise ValueError('Choix A/B/C inconnu.')
    if report.get('kind') != 'pro_c3_parameter_validation' or report.get('status') != 'needs_review':
        raise ValueError('Rapport de validation non admissible.')
    output = Path(root).resolve() / 'settings' / 'pro_c3_audition_preferences.jsonl'
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {'kind':'synthetic_pro_c3_listening_preference', 'schema_version':1,
              'recorded_utc':datetime.now(timezone.utc).isoformat(),
              'selected':selected, 'test_created_utc':report.get('created_utc'),
              'use_for_hermes':False, 'automatic_compression_enabled':False,
              'note':'Signal synthétique; aucune préférence musicale inférée.'}
    with output.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False)+'\n')
    return output


class ProC3AuditionDialog:
    """Lazy Qt wrapper; imports PySide6 only when a user opens the dialog."""
    def __init__(self, root, parent=None):
        from PySide6.QtCore import Qt, QUrl
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QMessageBox
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        self.Qt = Qt
        self.QUrl = QUrl
        self.QMessageBox = QMessageBox
        self.sources, self.report = audition_sources(root)
        self.root = Path(root)
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle('Pro-C 3 — Écoute A/B/C (signal synthétique)')
        self.dialog.resize(640, 300)
        layout = QVBoxLayout(self.dialog)
        heading = QLabel('A/B/C — Original / Gentle / Firm')
        heading.setStyleSheet('font-size:17px;font-weight:700;')
        layout.addWidget(heading)
        note = QLabel('Uniquement le signal synthétique de 4 s. Les rendus Pro-C 3 ont 64 frames de queue; aucun traitement sur tes chansons. Le changement conserve la position, mais Qt peut provoquer une brève coupure audio.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.player = QMediaPlayer(self.dialog)
        self.output = QAudioOutput(self.dialog)
        self.output.setVolume(.6)
        self.player.setAudioOutput(self.output)
        self.kind = 'original'
        self.pending_position = None
        self.pending_play = False
        self.switch_buttons = {}
        buttons = QHBoxLayout()
        for kind in KINDS:
            b = QPushButton(LABELS[kind]); buttons.addWidget(b)
            b.clicked.connect(lambda checked=False, k=kind: self.switch(k))
            self.switch_buttons[kind] = b
        layout.addLayout(buttons)
        controls = QHBoxLayout()
        self.play_btn = QPushButton('▶ Écouter')
        self.play_btn.clicked.connect(self.toggle)
        controls.addWidget(self.play_btn)
        self.stop_btn = QPushButton('■ Stop')
        self.stop_btn.clicked.connect(self.stop)
        controls.addWidget(self.stop_btn)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0,4000)
        self.seek.sliderReleased.connect(self._seek_to_slider)
        controls.addWidget(self.seek, 1)
        self.clock = QLabel('00:00 / 00:04')
        controls.addWidget(self.clock)
        layout.addLayout(controls)
        self.status = QLabel('Sélection A · Original — prêt.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        chosen = QHBoxLayout()
        chosen.addWidget(QLabel('Préférence pour ce test :'))
        for kind in KINDS:
            b = QPushButton('♡ '+ LABELS[kind])
            b.clicked.connect(lambda checked=False,k=kind: self.choose(k))
            chosen.addWidget(b)
        layout.addLayout(chosen)
        self.player.positionChanged.connect(self._position)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.playbackStateChanged.connect(self._playback_state)
        self.player.errorOccurred.connect(lambda *_: self.status.setText('Erreur audio : '+self.player.errorString()))
        self.dialog.finished.connect(lambda *_: self.stop())
        self.switch('original')

    def switch(self, kind):
        from PySide6.QtMultimedia import QMediaPlayer
        if kind not in KINDS:
            raise ValueError('Version audio inconnue.')
        if kind == self.kind and not self.player.source().isEmpty():
            return
        previously_playing = self.player.playbackState() == QMediaPlayer.PlayingState or self.pending_play
        # Only the original 4 seconds are valid test material; ignore the tail.
        self.pending_position = min(3999, max(0, self.player.position()))
        self.pending_play = previously_playing
        self.kind = kind
        self.player.stop()
        self.player.setSource(self.QUrl.fromLocalFile(str(self.sources[kind])))
        for name, button in self.switch_buttons.items():
            button.setStyleSheet('font-weight:700;' if name == kind else '')
        self.status.setText('Écoute : '+LABELS[kind]+' — position conservée (rechargement Qt possible).')

    def _media_status(self, status):
        from PySide6.QtMultimedia import QMediaPlayer
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            if self.pending_position is not None:
                p = self.pending_position
                play = self.pending_play
                self.pending_position = None
                self.pending_play = False
                self.player.setPosition(p)
                if play:
                    self.player.play()

    def _position(self, pos):
        pos = min(4000, max(0,int(pos)))
        if not self.seek.isSliderDown():
            self.seek.setValue(pos)
        self.clock.setText(f'00:{pos//1000:02d} / 00:04')
        if pos >= 4000:
            self.player.pause()

    def _seek_to_slider(self):
        self.pending_position = None
        self.player.setPosition(self.seek.value())

    def _playback_state(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        self.play_btn.setText('Ⅱ Pause' if state == QMediaPlayer.PlayingState else '▶ Écouter')

    def toggle(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        elif self.pending_position is not None:
            self.pending_play = True
        else:
            if self.player.position() >= 3900:
                self.player.setPosition(0)
            self.player.play()

    def stop(self):
        self.pending_position = None
        self.pending_play = False
        self.player.stop()

    def choose(self, kind):
        try:
            path = store_preference(self.root, self.report, kind)
        except (OSError, ValueError) as exc:
            self.QMessageBox.warning(self.dialog, 'Préférence non sauvegardée', str(exc))
            return
        self.status.setText('♡ Choix '+ LABELS[kind]+' enregistré. Préférence de laboratoire uniquement, non utilisée par Hermes.')

    def exec(self):
        return self.dialog.exec()
