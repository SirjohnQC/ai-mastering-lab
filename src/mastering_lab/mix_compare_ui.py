"""Integrated synchronized Auto Mix A/B/C comparison window (Qt + sounddevice)."""
from __future__ import annotations
from pathlib import Path
import json
from threading import RLock
import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt, QTimer, QObject, QThread, Signal, Slot, QSettings
from PySide6.QtGui import QShortcut, QKeySequence, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QMessageBox, QGridLayout, QGroupBox, QPlainTextEdit, QComboBox, QCheckBox, QProgressBar)
from .mix_comparison import load_comparison, VARIANT_ORDER, VARIANT_LABELS


class _EvaluationWorker(QObject):
    finished = Signal(object, object)
    phase = Signal(str)

    def __init__(self, report, model, use_hermes, use_vision=False, vision_model='qwen3-vl:4b'):
        super().__init__()
        self.report = report
        self.model = model
        self.use_hermes = use_hermes
        self.use_vision = use_vision
        self.vision_model = vision_model

    @Slot()
    def run(self):
        from .mix_evaluator import evaluate_comparison, local_hermes_evaluation
        try:
            self.phase.emit('1/3 · Mesures DSP des trois WAV…')
            evaluation = evaluate_comparison(self.report)
            ai = None
            ai_error = None
            pngs = None
            vision = None
            vision_error = None
            if self.use_vision:
                try:
                    from .spectral_vision import render_comparison_spectrograms, local_vision_review
                    self.phase.emit('2/3 · Génération des spectrogrammes…')
                    pngs = render_comparison_spectrograms(self.report)
                    self.phase.emit(f'2/3 · Analyse vision {self.vision_model} (attente Ollama)…')
                    vision = local_vision_review(pngs, model=self.vision_model)
                except Exception as exc:
                    vision_error = str(exc)
            if self.use_hermes:
                try:
                    self.phase.emit(f'3/3 · Évaluation Hermes ({self.model})…')
                    ai = local_hermes_evaluation(evaluation, model=self.model, timeout=120, vision_summary=vision)
                except Exception as exc:
                    ai_error = str(exc)
            self.finished.emit({'evaluation':evaluation,'hermes':ai,'ai_error':ai_error, 'spectrograms':pngs, 'vision':vision, 'vision_error':vision_error}, None)
        except Exception as exc:
            self.finished.emit(None, str(exc))


class _LoudnessWorker(QObject):
    finished = Signal(object, object)
    phase = Signal(str)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    @Slot()
    def run(self):
        try:
            from .loudness_match import match_files
            self.phase.emit('Mesure LUFS intégrés en cours (3 WAV)…')
            self.finished.emit(match_files(self.paths), None)
        except Exception as exc:
            self.finished.emit(None, str(exc))


class _Gen2Worker(QObject):
    finished = Signal(object, object)
    phase = Signal(str)

    def __init__(self, comparison, model, approval=None, project_root=None):
        super().__init__()
        self.comparison = comparison
        self.model = model
        self.approval = approval
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]

    @Slot()
    def run(self):
        try:
            from .auto_mix_gen2 import model_proposal, deterministic_proposal, render_generation, read_session
            read_session(self.comparison)
            if self.approval is None:
                from .mix_evaluator import evaluate_comparison
                self.phase.emit('1/2 · Mesures DSP pour proposition Gen 2…')
                measurements = evaluate_comparison(self.comparison)
                from .preference_learning import preference_context, preference_path
                preferences = preference_context(preference_path(self.project_root))
                measurements['user_preferences'] = preferences
                try:
                    self.phase.emit('2/2 · Hermes prépare la proposition…')
                    result = model_proposal(measurements, model=self.model)
                    result['preferences_used'] = bool(preferences)
                except Exception as error:
                    result = deterministic_proposal()
                    result['ai_error'] = str(error)[:500]
                    result['preferences_used'] = False
            else:
                self.phase.emit('Rendu des 3 WAV Gen 2 (progression non estimable)…')
                result = render_generation(self.comparison, self.approval, project_root=self.project_root)
            self.finished.emit(result, None)
        except Exception as exc:
            self.finished.emit(None, str(exc))


class _EQPlanWorker(QObject):
    finished = Signal(object, object)
    phase = Signal(str)

    def __init__(self, comparison, model):
        super().__init__()
        self.comparison = comparison
        self.model = model

    @Slot()
    def run(self):
        try:
            from .mix_evaluator import evaluate_comparison
            from .eq_plan import propose_eq_plan
            self.phase.emit('EQ : mesures DSP du prémix Balanced…')
            data = evaluate_comparison(self.comparison)
            self.phase.emit('EQ : Hermes propose des essais limités…')
            self.finished.emit(propose_eq_plan(data, model=self.model), None)
        except Exception as exc:
            self.finished.emit(None, str(exc))


class _EQAuditionWorker(QObject):
    finished = Signal(object, object)
    phase = Signal(str)

    def __init__(self, comparison, plan, project_root):
        super().__init__()
        self.comparison = comparison
        self.plan = plan
        self.project_root = project_root

    @Slot()
    def run(self):
        try:
            from .eq_audition import render_eq_audition
            result = render_eq_audition(self.comparison, self.plan,
                                        root=self.project_root,
                                        progress=self.phase.emit)
            self.finished.emit(result, None)
        except Exception as exc:
            self.finished.emit(None, str(exc))


class MixCompareDialog(QDialog):
    """One audio stream, same playhead for all versions; short crossfade on switches."""
    automaticAnalysisFinished = Signal(bool, str)
    def __init__(self, comparison, parent=None):
        super().__init__(parent)
        self.paths, spec = load_comparison(comparison)
        self.rate, self.channels, self.frames = spec
        self._lock = RLock()
        self._files = {key: sf.SoundFile(str(path), mode='r') for key,path in self.paths.items()}
        self._stream = None
        self._active = 'balanced'
        self._previous = None
        self._fade_remaining = 0
        self._fade_total = max(1, round(self.rate * 0.025))
        self._pos = 0
        self._playing = False
        self._vol = 0.8
        self._loudness_gains = {key: 1.0 for key in VARIANT_ORDER}
        self._loudness_matched = False
        self._loudness_thread = None
        self._loudness_worker = None
        self._evaluation_thread = None
        self._evaluation_worker = None
        self._comparison_source = comparison
        self._auto_review_pending = False
        self._auto_loudness_pending = False
        self._gen2_thread = None
        self._gen2_worker = None
        self._eq_thread = None
        self._eq_worker = None
        self._eq_audition_thread = None
        self._eq_audition_worker = None
        self._eq_plan = None
        self._eq_audition_dialog = None
        self._parent_comparison = None
        self.setWindowTitle('Auto Mix Compare — Balanced / Vocal Focus / Punchy')
        self.resize(920, 760)
        self._spectrogram_paths = {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Compare les 3 prémix au même endroit de la chanson. Raccourcis : 1 / 2 / 3.'))
        buttons = QGridLayout()
        self._buttons = {}
        for col,key in enumerate(VARIANT_ORDER):
            btn = QPushButton(f'{col + 1} · {VARIANT_LABELS[key]}')
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False,k=key:self.switch(k))
            buttons.addWidget(btn, 0, col)
            self._buttons[key] = btn
            QShortcut(QKeySequence(str(col+1)), self, activated=lambda k=key:self.switch(k))
        layout.addLayout(buttons)
        self._now = QLabel('Écoute : Balanced')
        layout.addWidget(self._now)
        transport = QHBoxLayout()
        self._play = QPushButton('▶ Play')
        self._play.clicked.connect(self.toggle_play)
        transport.addWidget(self._play)
        self._stop = QPushButton('■ Stop')
        self._stop.clicked.connect(self.stop)
        transport.addWidget(self._stop)
        self._seek = QSlider(Qt.Horizontal)
        self._seek.setRange(0, 10000)
        self._seek.sliderReleased.connect(self.seek)
        transport.addWidget(self._seek, 1)
        self._time = QLabel('00:00 / 00:00')
        transport.addWidget(self._time)
        layout.addLayout(transport)
        volume = QHBoxLayout()
        volume.addWidget(QLabel('Volume d’écoute'))
        self._volume = QSlider(Qt.Horizontal)
        self._volume.setRange(0,100)
        self._volume.setValue(80)
        self._volume.valueChanged.connect(self.set_volume)
        volume.addWidget(self._volume)
        layout.addLayout(volume)
        loudness_row = QHBoxLayout()
        self._match_check = QCheckBox('Level-match A/B/C (LUFS-I)')
        self._match_check.setEnabled(False)
        self._match_check.toggled.connect(self._set_loudness_matching)
        loudness_row.addWidget(self._match_check)
        self._match_btn = QPushButton('Measure LUFS for A/B/C')
        self._match_btn.clicked.connect(self._start_loudness)
        loudness_row.addWidget(self._match_btn)
        self._match_status = QLabel('Level match off — raw WAV playback')
        loudness_row.addWidget(self._match_status, 1)
        layout.addLayout(loudness_row)
        analysis_bar = QHBoxLayout()
        self._analyze_btn = QPushButton('📊 Analyze 3 mixes')
        self._analyze_btn.clicked.connect(lambda: self._start_evaluation(False))
        analysis_bar.addWidget(self._analyze_btn)
        self._hermes_btn = QPushButton('🧠 Hermes Mix Evaluator')
        self._hermes_btn.clicked.connect(lambda: self._start_evaluation(True))
        analysis_bar.addWidget(self._hermes_btn)
        self._vision_btn = QPushButton('👁 Spectrograms + Qwen Vision + Hermes')
        self._vision_btn.clicked.connect(lambda: self._start_evaluation(True, use_vision=True))
        analysis_bar.addWidget(self._vision_btn)
        layout.addLayout(analysis_bar)
        self._auto_vision_optin = QCheckBox('Inclure Qwen Vision dans Auto Studio (plus lent; optionnel)')
        self._auto_vision_optin.setChecked(False)
        layout.addWidget(self._auto_vision_optin)
        self._eq_plan_btn = QPushButton('🎚 Hermes → Pro-Q 4 (essais EQ · aperçu uniquement)')
        self._eq_plan_btn.clicked.connect(self._start_eq_plan)
        layout.addWidget(self._eq_plan_btn)
        self._eq_render_btn = QPushButton('🎧 Écouter EQ Before / After (vrai Pro-Q 4)')
        self._eq_render_btn.setEnabled(False)
        self._eq_render_btn.clicked.connect(self._start_eq_audition)
        layout.addWidget(self._eq_render_btn)
        self._gen2_btn = QPushButton('✨ Generate Gen 2 (Hermes → 3 new mixes)')
        self._gen2_btn.clicked.connect(self._start_gen2)
        layout.addWidget(self._gen2_btn)
        self._generation_label = QLabel()
        layout.addWidget(self._generation_label)
        self._generation_result_label = QLabel('')
        self._generation_result_label.setWordWrap(True)
        layout.addWidget(self._generation_result_label)
        self._back_generation_btn = QPushButton('← Retour à la génération précédente')
        self._back_generation_btn.clicked.connect(self._back_to_parent_generation)
        layout.addWidget(self._back_generation_btn)
        spectral_bar = QHBoxLayout()
        spectral_bar.addWidget(QLabel('Spectrogramme :'))
        self._spectral_pick = QComboBox()
        for key in VARIANT_ORDER:
            self._spectral_pick.addItem(VARIANT_LABELS[key], key)
        self._spectral_pick.currentIndexChanged.connect(self._show_spectrogram)
        spectral_bar.addWidget(self._spectral_pick)
        layout.addLayout(spectral_bar)
        self._spectrum_image = QLabel('Clique sur Spectrograms + Qwen Vision + Hermes pour générer les images.')
        self._spectrum_image.setAlignment(Qt.AlignCenter)
        self._spectrum_image.setMinimumHeight(100)
        self._spectrum_image.setMaximumHeight(240)
        layout.addWidget(self._spectrum_image)
        self._busy_bar = QProgressBar()
        self._busy_bar.setRange(0,0);self._busy_bar.setVisible(False)
        layout.addWidget(self._busy_bar)
        self._analysis_status = QLabel('Analyse disponible — sans modifier les fichiers audio.')
        layout.addWidget(self._analysis_status)
        self._analysis_text = QPlainTextEdit()
        self._analysis_text.setReadOnly(True)
        self._analysis_text.setMinimumHeight(165)
        self._analysis_text.setPlaceholderText('Les mesures comparatives et le rapport Hermes apparaîtront ici.')
        layout.addWidget(self._analysis_text)
        layout.addWidget(QLabel('Comparaison descriptive seulement : RMS ≠ LUFS, sample peak ≠ true peak.'))
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update_ui)
        self._timer.start()
        self._refresh_generation_label()
        self._sync_buttons()
        self._update_ui()

    def _sync_buttons(self):
        for key,btn in self._buttons.items():
            btn.setChecked(key == self._active)
        self._now.setText(f'Écoute : {VARIANT_LABELS[self._active]}')

    def switch(self, key):
        if key not in self._files or key == self._active:
            return
        with self._lock:
            # Short A/B crossfade, keeping the exact same absolute sample offset.
            self._previous = self._active if self._playing else None
            self._active = key
            self._fade_remaining = self._fade_total if self._playing else 0
        self._sync_buttons()

    def set_volume(self, value):
        with self._lock:
            self._vol = float(value)/100.0

    def toggle_play(self):
        if self._playing:
            with self._lock: self._playing = False
            self._play.setText('▶ Play')
            return
        try:
            if self._stream is None:
                import sounddevice as sd
                self._stream = sd.OutputStream(samplerate=self.rate, channels=2,
                                               dtype='float32', callback=self._audio_callback,
                                               blocksize=0, latency='high')
                self._stream.start()
            with self._lock:
                if self._pos >= self.frames: self._pos = 0
                self._previous = None
                self._fade_remaining = 0
                self._playing = True
            self._play.setText('❚❚ Pause')
        except Exception as exc:
            QMessageBox.warning(self,'Lecture impossible',
                f'Le périphérique audio ne peut pas être ouvert.\n\n{exc}\n\n'
                'Vérifie sounddevice et le périphérique de sortie Windows.')

    def stop(self):
        with self._lock:
            self._playing = False
            self._pos = 0
            self._previous = None
            self._fade_remaining = 0
        self._play.setText('▶ Play')
        self._update_ui()

    def seek(self):
        with self._lock:
            self._pos = min(self.frames, round(self.frames * self._seek.value()/10000))
            self._previous = None
            self._fade_remaining = 0

    @staticmethod
    def _fmt(frame, sample_rate):
        total = int(frame // sample_rate)
        return f'{total//60:02d}:{total%60:02d}'

    def _update_ui(self):
        with self._lock:
            position = self._pos
            running = self._playing
        self._time.setText(f'{self._fmt(position,self.rate)} / {self._fmt(self.frames,self.rate)}')
        if not self._seek.isSliderDown():
            self._seek.setValue(round(10000*position/self.frames))
        self._play.setText('❚❚ Pause' if running else '▶ Play')

    def _read(self, key, start, length):
        file = self._files[key]
        file.seek(start)
        return file.read(length, dtype='float32', always_2d=True)

    def _audio_callback(self, outdata, frames, time_info, status):
        outdata.fill(0)
        with self._lock:
            if not self._playing:
                return
            start = self._pos
            size = min(frames, self.frames-start)
            if size <= 0:
                self._playing = False
                return
            try:
                current = self._read(self._active, start, size)
                current_gain = self._loudness_gains[self._active] if self._loudness_matched else 1.0
                mixed = current * current_gain
                previous = self._previous
                if previous and self._fade_remaining > 0:
                    old = self._read(previous, start, size)
                    old_gain = self._loudness_gains[previous] if self._loudness_matched else 1.0
                    elapsed = self._fade_total - self._fade_remaining
                    blend = np.clip((elapsed + np.arange(size, dtype=np.float32) + 1) / self._fade_total, 0, 1)[:, None]
                    mixed = old * old_gain * (1 - blend) + mixed * blend
                    self._fade_remaining = max(0, self._fade_remaining - size)
                    if not self._fade_remaining:
                        self._previous = None
                outdata[:len(mixed)] = np.clip(mixed*self._vol,-1,1)
                self._pos += size
                if self._pos >= self.frames:self._playing = False
            except Exception:
                self._playing = False
                outdata.fill(0)

    def _set_loudness_matching(self, checked):
        with self._lock:
            self._loudness_matched = bool(checked)
        self._match_status.setText('Level matched' if checked else 'Raw WAV playback')

    def _busy_update(self, message):
        self._analysis_status.setText(message)

    def _busy_visible(self, active):
        self._busy_bar.setVisible(bool(active))

    def _start_loudness(self):
        if self._loudness_thread is not None:
            return
        self._match_btn.setEnabled(False)
        self._match_check.setEnabled(False)
        self._match_status.setText('Measuring integrated LUFS…')
        self._busy_visible(True)
        thread = QThread(self)
        worker = _LoudnessWorker({k: str(v) for k, v in self.paths.items()})
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.phase.connect(self._busy_update)
        worker.finished.connect(self._loudness_done)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._loudness_cleanup)
        self._loudness_thread, self._loudness_worker = thread, worker
        thread.start()

    def _loudness_done(self, data, error):
        if error:
            self._match_status.setText('LUFS measurement failed')
            if self._auto_loudness_pending:
                self._auto_loudness_pending = False
                self._generation_result_label.setText(
                    f'GEN {getattr(self, "_current_generation", 1)} · 3 WAV prêts · analyse partielle : LUFS indisponibles.'
                )
                self.automaticAnalysisFinished.emit(False, 'mesure LUFS indisponible : ' + str(error))
            else:
                QMessageBox.warning(self, 'Level matching', error)
            return
        with self._lock:
            self._loudness_gains = data['gains']
        self._match_check.setEnabled(True)
        self._match_check.setChecked(True)
        self._match_status.setText(' / '.join(
            f"{VARIANT_LABELS[k]} {data['measurements'][k]['lufs_i']:.1f} LUFS"
            for k in VARIANT_ORDER))
        if self._auto_loudness_pending:
            self._auto_loudness_pending = False
            self._generation_result_label.setText(
                f'GEN {getattr(self, "_current_generation", 1)} · 3 WAV prêts · DSP, Hermes et LUFS terminés. '
                'Écoute Balanced / Vocal Focus / Punchy à niveau égalisé pour choisir.'
            )
            self.automaticAnalysisFinished.emit(True, 'DSP / Hermes / LUFS terminés')

    def _loudness_cleanup(self):
        self._loudness_thread = None
        self._loudness_worker = None
        self._match_btn.setEnabled(True)
        self._busy_visible(False)

    def _show_spectrogram(self, *_):
        key = self._spectral_pick.currentData()
        if key in self._spectrogram_paths:
            pix = QPixmap(self._spectrogram_paths[key])
            if not pix.isNull():
                self._spectrum_image.setPixmap(pix.scaled(820, 215, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _start_evaluation(self, use_hermes, use_vision=False):
        if self._evaluation_thread is not None:
            return
        from .ai_settings_ui import read_ai_preferences
        preferences = read_ai_preferences(Path(__file__).resolve().parents[2])
        model = preferences['model']
        vision_model = preferences['vision_model']
        self._analyze_btn.setEnabled(False)
        self._hermes_btn.setEnabled(False)
        self._vision_btn.setEnabled(False)
        self._busy_visible(True)
        self._analysis_status.setText('Analyse des trois WAV' + (' + vision Qwen + Hermes…' if use_vision else (' + requête Hermes locale…' if use_hermes else '…')))
        thread = QThread(self)
        worker = _EvaluationWorker(self._comparison_source, model, use_hermes, use_vision, vision_model)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.phase.connect(self._busy_update)
        worker.finished.connect(self._evaluation_done)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._evaluation_cleanup)
        self._evaluation_thread, self._evaluation_worker = thread, worker
        thread.start()

    def _evaluation_cleanup(self):
        self._evaluation_thread = None
        self._evaluation_worker = None
        self._analyze_btn.setEnabled(True)
        self._hermes_btn.setEnabled(True)
        self._vision_btn.setEnabled(True)
        self._busy_visible(False)

    def start_automatic_analysis(self):
        """Evaluate first; measure LUFS afterward to avoid competing analyses."""
        if self._evaluation_thread is not None or self._loudness_thread is not None:
            return
        self._auto_review_pending = True
        self._auto_loudness_pending = True
        # Qwen3-VL may exhaust its output budget thinking over three PNGs.
        # Do not let this optional feature hold the one-click flow hostage.
        self._analysis_status.setText('Auto Studio : analyse DSP + Hermes; Qwen Vision facultatif.')
        self._start_evaluation(True, use_vision=self._auto_vision_optin.isChecked())

    def _evaluation_done(self, result, error):
        if error:
            self._analysis_status.setText('Analyse impossible')
            self._analysis_text.setPlainText(error)
            if self._auto_review_pending:
                self._auto_review_pending=False
                QTimer.singleShot(200,self._start_loudness)
            return
        if result.get('spectrograms'):
            self._spectrogram_paths = result['spectrograms']
            self._show_spectrogram()
        data = result['evaluation']
        lines = ['MESURES AUDIO — comparaison relative à Balanced',
                 'RMS / crête échantillon / crest (dB), corrélation stéréo']
        for key in VARIANT_ORDER:
            m = data['metrics'][key]
            d = data['differences'][key]
            corr = 'n/a' if m['stereo_correlation'] is None else str(m['stereo_correlation'])
            lines.append(f"{VARIANT_LABELS[key]}: RMS {m['rms_dbfs']:.2f} | Peak {m['sample_peak_dbfs']:.2f} | Crest {m['crest_db']:.2f} | Stereo {corr} | Δ RMS {d['rms_delta_db']:+.2f} dB")
            if m['clipped_samples']:
                lines.append(f"  ATTENTION : {m['clipped_samples']} échantillons à/amont de ±1.0")
        lines.extend(['', 'Énergie spectrale indicative (sub / bas-médiums / médiums / aiguës) :'])
        for key in VARIANT_ORDER:
            bands = data['metrics'][key]['spectral_shares']
            lines.append(f"{VARIANT_LABELS[key]} : " + ' / '.join(f'{100*v:.1f}%' for v in bands.values()))
        lines.extend(['', *data['notes']])
        if result['hermes']:
            report=result['hermes']
            lines.extend(['', 'HERMES — analyse des mesures (pas une écoute du son)',
                          report.get('summary',''),
                          *('• '+item for item in report.get('observations',[])),
                          'Proposition : ' + report.get('recommendation',''),
                          *('Limite : '+item for item in report.get('caveats',[]))])
        if result.get('vision'):
            lines.extend(['', 'QWEN3-VL — observations des spectrogrammes uniquement',
                          *('• '+x for x in result['vision'].get('observations', [])),
                          *('Limite : '+x for x in result['vision'].get('limits', []))])
        if result.get('vision_error'):
            lines.extend(['', 'Vision indisponible : '+result['vision_error']])
        if result['ai_error']:
            lines.extend(['', 'Hermes indisponible : '+result['ai_error'],
                          'Les mesures techniques ci-dessus restent valides.'])
        self._analysis_text.setPlainText('\n'.join(lines))
        self._analysis_status.setText('Analyse terminée' + (' (Hermes indisponible)' if result['ai_error'] else '') + (' · Qwen Vision facultatif indisponible' if result.get('vision_error') else ''))
        if self._auto_review_pending:
            self._auto_review_pending=False
            QTimer.singleShot(200,self._start_loudness)

    def _start_eq_plan(self):
        if self._eq_thread is not None or self._evaluation_thread is not None or self._gen2_thread is not None:
            return
        from .ai_settings_ui import read_ai_preferences
        preferences = read_ai_preferences(Path(__file__).resolve().parents[2])
        self._eq_plan_btn.setEnabled(False)
        self._busy_visible(True)
        thread = QThread(self)
        worker = _EQPlanWorker(self._comparison_source, preferences['model'])
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.phase.connect(self._busy_update)
        worker.finished.connect(self._eq_plan_done)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._eq_plan_cleanup)
        self._eq_thread, self._eq_worker = thread, worker
        thread.start()

    def _eq_plan_done(self, result, error):
        if error:
            self._analysis_status.setText('Essais Pro-Q 4 indisponibles : ' + error[:180])
            QMessageBox.warning(self, 'Hermes EQ Plan', error)
            return
        from .eq_plan import format_plan
        self._eq_plan = result
        self._eq_render_btn.setEnabled(bool(result.get('moves')))
        self._analysis_text.appendPlainText('\n\n' + format_plan(result))
        self._analysis_status.setText('Essais EQ proposés — aucun plugin modifié.')

    def _eq_plan_cleanup(self):
        self._eq_thread = None
        self._eq_worker = None
        self._eq_plan_btn.setEnabled(True)
        self._busy_visible(False)

    def _start_eq_audition(self):
        if (self._eq_audition_thread is not None or self._eq_thread is not None
                or self._gen2_thread is not None or self._evaluation_thread is not None):
            return
        if not self._eq_plan or not self._eq_plan.get('moves'):
            QMessageBox.information(self, 'EQ', 'Commence par obtenir un plan Hermes valide.')
            return
        if QMessageBox.question(
                self, 'Essai Pro-Q 4',
                'Appliquer les corrections proposées au prémix Balanced avec le vrai FabFilter Pro-Q 4 ?\n\n'
                'Un nouveau WAV sera créé sans modifier les stems ni les mixages originaux.\n'
                'Le host calibrera les fréquences et vérifiera les valeurs réelles du plugin. '
                'Le traitement peut prendre du temps.',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._eq_render_btn.setEnabled(False)
        self._busy_visible(True)
        thread = QThread(self)
        worker = _EQAuditionWorker(self._comparison_source, self._eq_plan,
                                   Path(__file__).resolve().parents[2])
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.phase.connect(self._busy_update)
        worker.finished.connect(self._eq_audition_done)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._eq_audition_cleanup)
        self._eq_audition_thread, self._eq_audition_worker = thread, worker
        thread.start()

    def _eq_audition_done(self, result, error):
        if error:
            self._analysis_status.setText('Pro-Q 4 : essai indisponible — ' + error[:180])
            QMessageBox.warning(self, 'Essai EQ impossible', error)
            return
        self._analysis_status.setText('Essai Pro-Q 4 prêt — WAV original conservé.')
        self._analysis_text.appendPlainText('\n\nESSAI PRO-Q 4 RENDU (NON MASTERISÉ)\n'
                                            'Original : ' + result['original'] + '\n'
                                            'Essai : ' + result['after'])
        try:
            audition = MixCompareDialog(result['comparison'], self)
            audition.setWindowTitle('EQ BEFORE / AFTER — FabFilter Pro-Q 4 · Essai non destructif')
            audition._buttons['balanced'].setText('1 · BEFORE (Balanced)')
            audition._buttons['vocal-focus'].setText('2 · AFTER (Pro-Q 4)')
            audition._buttons['punchy'].setText('3 · Original (duplicata)')
            audition._buttons['punchy'].setEnabled(False)
            audition._generation_label.setText('EQ Before / After — sans modification du mix original')
            # Keep alive while the non-modal dialog is on screen.
            self._eq_audition_dialog = audition
            audition.show()
            audition.raise_()
            QTimer.singleShot(250, audition._start_loudness)
        except Exception as exc:
            QMessageBox.warning(self, 'Comparateur EQ',
                                'WAV EQ créé, mais comparateur non ouvert : ' + str(exc))

    def _eq_audition_cleanup(self):
        self._eq_audition_thread = None
        self._eq_audition_worker = None
        self._eq_render_btn.setEnabled(bool(self._eq_plan and self._eq_plan.get('moves')))
        self._busy_visible(False)

    def _start_gen2(self):
        if self._gen2_thread is not None or self._evaluation_thread is not None:
            return
        from .auto_mix_gen2 import read_session
        try:
            read_session(self._comparison_source)
        except Exception as exc:
            QMessageBox.information(self, 'Gen 2 — session initiale requise', str(exc))
            return
        root = getattr(self.parent(), 'root', Path(__file__).resolve().parents[2])
        model = 'hermes3:8b'
        try:
            import json
            settings = root / 'settings' / 'ai_review.json'
            if settings.is_file():
                model = json.loads(settings.read_text(encoding='utf-8')).get('model', model)
        except Exception:
            pass
        self._launch_gen2_worker(model)

    def _launch_gen2_worker(self, model, approval=None):
        self._gen2_btn.setEnabled(False)
        self._busy_visible(True)
        self._analysis_status.setText('Hermes prépare les ajustements…' if approval is None else 'Rendu Gen 2 des trois WAV…')
        thread = QThread(self)
        worker = _Gen2Worker(self._comparison_source, model, approval,
                             project_root=getattr(self.parent(), 'root', None))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.phase.connect(self._busy_update)
        worker.finished.connect(self._gen2_done)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._gen2_cleanup)
        self._gen2_thread = thread
        self._gen2_worker = worker
        self._gen2_rendering = approval is not None
        thread.start()

    def _gen2_cleanup(self):
        self._gen2_thread = None
        self._gen2_worker = None
        self._gen2_btn.setEnabled(True)
        self._busy_visible(False)
        pending = getattr(self, '_gen2_pending', None)
        completed = getattr(self, '_gen2_completed', None)
        self._gen2_pending = None
        self._gen2_completed = None
        if pending is not None:
            QTimer.singleShot(0, lambda p=pending: self._review_gen2_proposal(p))
        if completed is not None:
            QTimer.singleShot(0, lambda p=completed: self._open_gen2_comparison(p))

    def _gen2_done(self, result, error):
        if error:
            self._analysis_status.setText('Gen 2 impossible : ' + error[:200])
            QMessageBox.warning(self, 'Auto Mix Gen 2', error)
            return
        if self._gen2_rendering:
            self._analysis_status.setText('Gen 2 : 3 WAV rendus; chargement et analyse automatique…')
            self._gen2_completed = result['comparison']
        else:
            self._gen2_pending = result

    def _refresh_generation_label(self):
        """Use the actual report metadata rather than guessing from its filename."""
        generation = 1
        parent = None
        try:
            if isinstance(self._comparison_source, (str, Path)):
                data = json.loads(Path(self._comparison_source).read_text(encoding='utf-8'))
            else:
                data = self._comparison_source
            generation = max(1, int(data.get('generation', 1)))
            if data.get('parent_comparison'):
                candidate = Path(data['parent_comparison'])
                if not candidate.is_absolute() and isinstance(self._comparison_source, (str, Path)):
                    candidate = Path(self._comparison_source).resolve().parent / candidate
                parent = candidate.resolve()
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
        self._parent_comparison = parent
        self._current_generation = generation
        # Each approved pass gets its own files and an explicit parent report.
        self._gen2_btn.setVisible(True)
        self._gen2_btn.setText(f'Créer la génération {generation + 1}')
        self._generation_label.setText(f'🎧 Génération {generation} — comparaison A/B/C')
        self.setWindowTitle(f'Auto Mix Compare — GEN {generation} — Balanced / Vocal Focus / Punchy')
        self._back_generation_btn.setVisible(parent is not None)

    def _back_to_parent_generation(self):
        if self._parent_comparison is None:
            return
        self._load_comparison_in_place(self._parent_comparison)

    def _load_comparison_in_place(self, report_path):
        """Swap Gen 1/Gen 2 in the existing dialog without opening another player."""
        if any(thread is not None for thread in
               (self._evaluation_thread, self._gen2_thread, self._loudness_thread, self._eq_audition_thread)):
            QMessageBox.information(self, 'Traitement en cours',
                'Attends la fin de l’analyse avant de changer de génération.')
            return
        try:
            new_paths, new_spec = load_comparison(report_path)
            # Open everything first, so a failed report does not disturb playback.
            new_files = {}
            try:
                for key, path in new_paths.items():
                    new_files[key] = sf.SoundFile(str(path), mode='r')
            except Exception:
                for opened in new_files.values():
                    opened.close()
                raise
        except Exception as exc:
            QMessageBox.warning(self, 'Changement de génération impossible', str(exc))
            return

        # Stop the output callback before closing the old files; never close them
        # while sounddevice may be reading inside _audio_callback.
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            old_files = self._files
            self._files = new_files
            self.paths = new_paths
            self.rate, self.channels, self.frames = new_spec
            self._comparison_source = Path(report_path).resolve()
            self._pos = 0
            self._playing = False
            self._previous = None
            self._fade_remaining = 0
            self._fade_total = max(1, round(self.rate * 0.025))
            self._active = 'balanced'
            self._loudness_gains = {key: 1.0 for key in VARIANT_ORDER}
            self._loudness_matched = False
        for old in old_files.values():
            try:old.close()
            except Exception:pass

        # Results and level matching belong to one generation, not to all WAVs.
        self._match_check.setChecked(False)
        self._match_check.setEnabled(False)
        self._match_status.setText('Level match off — mesure LUFS à refaire pour cette génération')
        self._spectrogram_paths = {}
        self._spectrum_image.clear()
        self._spectrum_image.setText('Clique sur Spectrograms + Qwen Vision + Hermes pour générer les images.')
        self._analysis_text.clear()
        self._analysis_status.setText('Génération chargée — analyse disponible.')
        self._eq_plan = None
        self._eq_render_btn.setEnabled(False)
        self._spectral_pick.setCurrentIndex(0)
        self._refresh_generation_label()
        self._generation_result_label.setText(
            f'GEN {self._current_generation} chargée · trois WAV prêts · nouvelle analyse disponible.'
        )
        self._sync_buttons()
        self._update_ui()
        return True

    def _open_gen2_comparison(self, report_path):
        # Do not open a second dialog or show a popup just to announce WAV files.
        # The render thread has already finished and released its QThread state.
        if self._load_comparison_in_place(report_path):
            self._generation_result_label.setText(
                f'GEN {self._current_generation} · trois nouveaux WAV prêts. Analyse DSP → Hermes → LUFS automatique en cours…'
            )
            self._analysis_status.setText('Gen 2 · analyse automatique des trois nouveaux WAV…')
            QTimer.singleShot(150, self.start_automatic_analysis)

    def _review_gen2_proposal(self, proposal):
        from .auto_mix_gen2 import LABELS, GROUPS
        lines = []
        for name in LABELS:
            changes = ', '.join(f'{group} {proposal["deltas"][name][group]:+g} dB' for group in GROUPS)
            lines.append(f'{name}: {changes}')
        message = ('Générer trois nouveaux prémix à partir des réglages actuels ?\n\n'
                   + '\n'.join(lines)
                   + '\n\nRaison : ' + proposal.get('reason', '')
                   + ('\n\nPréférences et notes transmises à Hermes.' if proposal.get('preferences_used')
                      else '\n\nAucune préférence utilisée pour cette proposition.')
                   + ('\n\nHermes indisponible : ' + proposal['ai_error'] if proposal.get('ai_error') else '')
                   + '\n\nLes WAV originaux ne seront pas modifiés. '
                     'Variations max ±1 dB par famille, pas de changements VST ou EQ.\n'
                     'Hermes n’a pas écouté l’audio.')
        if QMessageBox.question(self, 'Valider Auto Mix Gen 2', message,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self._launch_gen2_worker(proposal.get('model') or 'hermes3:8b', approval=proposal)
        else:
            self._analysis_status.setText('Gen 2 annulée — aucun WAV modifié.')

    def closeEvent(self, event):
        if ((self._evaluation_thread is not None and self._evaluation_thread.isRunning())
                or (self._gen2_thread is not None and self._gen2_thread.isRunning())
                or (self._loudness_thread is not None and self._loudness_thread.isRunning())
                or (self._eq_audition_thread is not None and self._eq_audition_thread.isRunning())):
            QMessageBox.information(self, 'Analyse en cours',
                'L’analyse audio / Hermes est en cours. Ferme cette fenêtre après son résultat.')
            event.ignore()
            return
        self._timer.stop()
        with self._lock:self._playing=False
        if self._stream is not None:
            try:self._stream.stop();self._stream.close()
            except Exception:pass
            self._stream=None
        for file in self._files.values():
            try:file.close()
            except Exception:pass
        super().closeEvent(event)
