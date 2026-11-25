"""Integrated nine-way comparison: three premixes x three *opt-in* Pro-C 3 copies.

Never changes the originals. Only an explicitly heart-approved compression path can be
handed to mastering; A/B/C audition alone is never an approval.
"""
from __future__ import annotations

from pathlib import Path
import json
import hashlib
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QCheckBox, QFrame, QMessageBox
from .waveform_preview import WaveformStrip
from .compare_visual_diagnostics import measure_combinations
from .compression_advisor import suggest_compression
from .ai_compression_decision import decide_compressions, _safe_choice
from .compression_explainer import explain_gentle, _threshold_from_report
from .compression_activity import inspect_threshold_activity, interpret_activity
from .pro_c3_song_preview import make_preview, audition_files, verify_source, save_choice
from .pro_c3_loudness_match import preview_volume, BASE_VOLUME

CACHE_RENDER_VERSION = 3  # v0.23.9: two smart Gentle trials; invalidate earlier fixed Gentle renders
MIXES = ('balanced', 'vocal-focus', 'punchy')
COMPRESSIONS = ('original', 'gentle', 'firm')
MIX_NAMES = {'balanced':'Balanced', 'vocal-focus':'Vocal Focus', 'punchy':'Punchy'}
COMP_NAMES = {'original':'Original', 'gentle':'Gentle', 'firm':'Firm'}


def session_fingerprint(paths):
    """Change cache identity if any premix is replaced, edited or moved."""
    entries = [['preview_render_schema',CACHE_RENDER_VERSION]]
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
                        self.completed.emit(self._attach_ai_decisions(self._attach_diagnostics(dict(cache['result'], cached=True), fingerprint), fingerprint))
                        return
                except (OSError, ValueError, TypeError, KeyError):
                    pass
            data = {}
            for key in MIXES:
                result = make_preview(self.root, self.paths[key], song_aware=True, smart_gentle=True)
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
            self.completed.emit(self._attach_ai_decisions(self._attach_diagnostics(payload, fingerprint), fingerprint))
        except Exception as exc:
            self.completed.emit({'status':'failed', 'error': f'{type(exc).__name__}: {exc}'})

    def _attach_diagnostics(self, payload, fingerprint):
        """Diagnosis runs on the render worker and never blocks preview on error."""
        try:
            folder = self.root / 'settings'
            path = folder / 'pro_c3_unified_diagnostics.json'
            if path.is_file():
                try:
                    cache = json.loads(path.read_text(encoding='utf-8'))
                    if cache.get('fingerprint') == fingerprint and cache.get('diagnostics_version') == 4:
                        payload['diagnostics'] = cache['results']
                        return payload
                except (OSError, ValueError, TypeError, KeyError):
                    pass
            files = {(mix, comp): Path(payload['mixes'][mix]['paths'][comp])
                     for mix in MIXES for comp in COMPRESSIONS}
            report = measure_combinations(files)
            # Input activity is always computed from the session's Original
            # PCM. Thresholds come from validated JUCE physical readback,
            # never from normalized parameter coordinates.
            for mix in MIXES:
                session_report = payload['mixes'][mix]['report']
                original = files[(mix, 'original')]
                for comp in ('gentle', 'firm'):
                    key = mix + '/' + comp
                    threshold_db = _threshold_from_report(session_report, comp)
                    try:
                        report['metrics'][key]['threshold_activity'] = (
                            inspect_threshold_activity(original, threshold_db))
                    except (OSError, ValueError, TypeError) as exc:
                        report['metrics'][key]['threshold_activity'] = {
                            'status':'unavailable', 'reason':str(exc)}
            payload['diagnostics'] = report
            folder.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.json.tmp')
            temp.write_text(json.dumps(
                {'fingerprint': fingerprint, 'diagnostics_version': 4, 'results': report},
                ensure_ascii=False), encoding='utf-8')
            temp.replace(path)
        except Exception as exc:
            payload['diagnostics_error'] = str(exc)
        return payload

    def _attach_ai_decisions(self, payload, fingerprint):
        """One local model request per unchanged 3-mix session, never an audio upload."""
        if payload.get('status') != 'ready':
            return payload
        folder = self.root / 'settings'
        path = folder / 'pro_c3_unified_ai_compression.json'
        # Cache is advisory only; the widget revalidates any selected option
        # against CURRENT PCM eligibility before offering audition.
        if path.is_file():
            try:
                cache = json.loads(path.read_text(encoding='utf-8'))
                if (cache.get('fingerprint') == fingerprint and
                        cache.get('decision_schema') == 1 and
                        cache.get('report') and
                        cache['report'].get('mode') in ('hermes','pcm_fallback')):
                    payload['ai_compression'] = cache['report']
                    return payload
            except (OSError, ValueError, KeyError, TypeError):
                pass
        decision = decide_compressions(payload.get('diagnostics', {}).get('metrics', {}),
                                       {mix:payload['mixes'][mix]['report'] for mix in MIXES})
        payload['ai_compression'] = decision
        try:
            folder.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.json.tmp')
            temp.write_text(json.dumps({'fingerprint':fingerprint,
                                        'decision_schema':1,'report':decision},
                                       ensure_ascii=False),encoding='utf-8')
            temp.replace(path)
        except (OSError, TypeError, ValueError):
            pass
        return payload


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
        self._diagnostics = {}
        self._ai_compression = {}
        self._intensity = 'balanced'
        self._advisor_choice = 'original'
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
        ver = QLabel('v0.24.0')
        ver.setStyleSheet('color:#9da4b4;font-size:11px;')
        header.addWidget(ver)
        layout.addLayout(header)
        self.recommendation = QLabel('✦ Hermes : recommandation de mix en attente · Pro-C 3 adaptatif basé sur des mesures PCM, pas Hermes')
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
        self.waveform.markerClicked.connect(self._jump_to_marker)
        layout.addWidget(self.waveform)
        self.file_status = QLabel('Fichier actif : en attente')
        self.file_status.setStyleSheet('color:#aab7cf;font-size:11px;')
        layout.addWidget(self.file_status)
        self.measure_status = QLabel('Mesures WAV : en attente')
        self.measure_status.setWordWrap(True)
        self.measure_status.setStyleSheet('color:#b8c1d3;font-size:11px;')
        layout.addWidget(self.measure_status)
        self.smart_gentle_status = QLabel('Smart Gentle : essais en attente')
        self.smart_gentle_status.setWordWrap(True)
        self.smart_gentle_status.setStyleSheet('color:#d5c5f6;font-size:11px;')
        layout.addWidget(self.smart_gentle_status)
        self.gentle_explanation = QLabel('Gentle : diagnostic en attente')
        self.gentle_explanation.setWordWrap(True)
        self.gentle_explanation.setStyleSheet(
            'color:#b9d6c6;font-size:11px;padding:5px 0;')
        layout.addWidget(self.gentle_explanation)
        self.activity_inspector = QLabel('Activité du signal au seuil : en attente')
        self.activity_inspector.setWordWrap(True)
        self.activity_inspector.setStyleSheet(
            'color:#b8c6ea;font-size:11px;padding:4px 0;')
        layout.addWidget(self.activity_inspector)
        self.marker_title = QLabel('Passages à comparer · Original ↔ compression')
        self.marker_title.setStyleSheet('color:#aab7cf;font-size:11px;')
        layout.addWidget(self.marker_title)
        marker_row = QHBoxLayout()
        self.marker_buttons = []
        for index in range(3):
            button = QPushButton('Écoute ' + str(index+1))
            button.setVisible(False)
            button.setEnabled(False)
            button.clicked.connect(lambda _=False, i=index: self._jump_to_marker(i))
            self.marker_buttons.append(button)
            marker_row.addWidget(button, 1)
        layout.addLayout(marker_row)
        self._active_markers = []
        self._marker_reference = None
        advisor_title = QLabel('3. Suggestion de compression (mesures WAV)')
        advisor_title.setStyleSheet('font-size:13px;font-weight:700;color:#f3f3f7;')
        layout.addWidget(advisor_title)
        advisory_row = QHBoxLayout()
        self.intensity_buttons = {}
        for key, label in (('natural','Naturel'), ('balanced','Équilibré'), ('punchy','Énergique')):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, v=key: self.set_intensity(v))
            advisory_row.addWidget(b, 1)
            self.intensity_buttons[key] = b
        layout.addLayout(advisory_row)
        self.advisor_status = QLabel('Suggestion disponible après analyse des WAV. Ce n’est pas un choix Hermes.')
        self.advisor_status.setWordWrap(True)
        self.advisor_status.setTextFormat(Qt.PlainText)
        self.advisor_status.setStyleSheet('color:#c7b8ff;font-size:11px;')
        layout.addWidget(self.advisor_status)
        self.audition_suggestion = QPushButton('▶ Écouter la suggestion (sans approuver)')
        self.audition_suggestion.setEnabled(False)
        self.audition_suggestion.clicked.connect(self.preview_suggestion)
        layout.addWidget(self.audition_suggestion)
        self._update_intensity_styles()
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
            self.recommendation.setText('✦ Hermes recommande le mix : ' + MIX_NAMES[mix] + ' · Compression Pro-C 3 : analyse PCM distincte, PAS une décision Hermes' + ref + '.')

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
        self._diagnostics = {}
        self._ai_compression = {}
        self._marker_reference = None
        self._advisor_choice = 'original'
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

    def _jump_to_marker(self, index):
        """Seek ALL nine players to the same locally measured position."""
        if not self._players or not self._loaded or index >= len(self._active_markers):
            return
        marker = self._active_markers[index]
        target = int(marker['seek_ms'])
        if target < 0 or target > self._max_ms:
            return
        self.seek.setValue(target)
        self._seek()
        self._position(self._active, target)
        # The shared transport starts audition only if playback is stopped.
        if not self._running:
            self.toggle()

    def _set_review_markers(self, markers):
        self._active_markers = [
            item for item in (markers or [])[:3]
            if isinstance(item, dict) and
            isinstance(item.get('seek_ms'), int) and
            0 <= item['seek_ms'] <= self._max_ms
        ]
        self.waveform.setMarkers([
            item['source_ms'] / max(1, self._max_ms)
            for item in self._active_markers
        ])
        for index, button in enumerate(self.marker_buttons):
            if index < len(self._active_markers):
                item = self._active_markers[index]
                ms = item['source_ms']
                stamp = f'{ms//60000:02d}:{ms//1000%60:02d}'
                button.setText('▶ ' + stamp)
                button.setToolTip(
                    'Passage suggéré · différence RMS locale : '
                    + str(item['rms_delta_db']) + ' dB. Écoute et compare à Original.')
                button.setEnabled(bool(self._players))
                button.setVisible(True)
            else:
                button.setEnabled(False)
                button.setVisible(False)
        comparison = COMP_NAMES.get(self._marker_reference or '', '')
        self.marker_title.setText(
            'Repères roses : passages à comparer avec ' + comparison
            + ' (différences PCM, pas nécessairement des défauts)'
            if self._active_markers else
            'Aucun repère mesurable pour ce mix : essaye Gentle ou Firm.')

    def _waveform_seek(self, fraction):
        if not self._players:return
        self.seek.setValue(round(self._max_ms * max(0.0,min(1.0,fraction))))
        self._seek()

    def set_waveform(self, envelope):
        # Once render diagnostics are ready, each compression gets its OWN
        # measured waveform. Do not let the legacy mix waveform overwrite it.
        if not self._files or not self._diagnostics.get('envelopes'):
            self.waveform.setData(envelope)

    def _update_active_diagnostics(self):
        key = '/'.join(self._active)
        if self._files.get(self._active):
            path = self._files[self._active]
            self.file_status.setText('WAV actif : ' + str(path))
            if self._active in self._players:
                self.file_status.setToolTip(str(path))
        wave = self._diagnostics.get('envelopes', {}).get(key)
        if wave:
            self.waveform.setData(np.asarray(wave, dtype=np.float32))
        metrics = self._diagnostics.get('metrics', {}).get(key)
        if not metrics:
            self.gentle_explanation.setText('Gentle : diagnostic indisponible.')
            self.activity_inspector.setText('Activité du signal au seuil : mesures indisponibles.')
            self._set_review_markers([])
            self.measure_status.setText('Mesures indisponibles : impossible de vérifier les différences WAV.')
            self._update_advisor()
            return
        smart = self._reports.get(self._active[0], {}).get('smart_gentle', {})
        if smart.get('status') == 'selected':
            selected = next((x for x in smart.get('candidates', [])
                             if x.get('name') == smart.get('selected')), {})
            metrics_trial = selected.get('metrics', {})
            self.smart_gentle_status.setText(
                'Smart Gentle : ' + str(len(smart.get('candidates', [])))
                + ' essais validés JUCE · seuil retenu : '
                + str(selected.get('parameters', {}).get('threshold', {}).get('plugin_text', '?'))
                + ' · variation RMS des fenêtres fortes : '
                + str(metrics_trial.get('window_analysis', {}).get('loud_rms_delta_db', '?'))
                + ' dB. Écoute avant ♥.')
        elif smart.get('status') == 'fallback_original':
            self.smart_gentle_status.setText(
                'Smart Gentle : aucun des deux essais n’a satisfait les contrôles.'
                ' Le choix Gentle joue donc Original; ♥ Gentle désactivé.')
        else:
            self.smart_gentle_status.setText('Smart Gentle : calibration indisponible.')
        diagnosis = explain_gentle(self._diagnostics.get('metrics', {}),
                                  self._active[0],
                                  self._reports.get(self._active[0], {}))
        if diagnosis.get('status') == 'unavailable':
            self.gentle_explanation.setText('Gentle : mesures insuffisantes pour expliquer son effet.')
        else:
            details = diagnosis.get('evidence', {})
            threshold = details.get('threshold_readback_db')
            info = (' · Seuil Pro-C 3 relu : ' + str(threshold) + ' dB'
                    if threshold is not None else ' · Seuil physique indisponible')
            self.gentle_explanation.setText('Pourquoi Gentle est-il discret? '
                                            + diagnosis['reason'] + info)
        inspection_comp = self._active[1] if self._active[1] != 'original' else 'gentle'
        inspection = self._diagnostics.get('metrics', {}).get(
            self._active[0] + '/' + inspection_comp, {}).get('threshold_activity', {})
        if inspection.get('status') == 'measured':
            rms_difference = self._diagnostics.get('metrics', {}).get(
                self._active[0] + '/' + inspection_comp, {}).get('rms_delta_db')
            interpretation = interpret_activity(inspection, rms_difference)
            self.activity_inspector.setText(
                'Activité source au seuil ' + COMP_NAMES[inspection_comp]
                + ' (' + str(inspection['threshold_db']) + ' dB) : '
                + str(inspection['peak_above_threshold_pct']) + '% des fenêtres en crête · '
                + str(inspection['rms_above_threshold_pct']) + '% en RMS · '
                + 'plus longue séquence RMS : '
                + str(inspection['longest_rms_run_ms']) + ' ms. '
                + interpretation['message']
                + ' (Ce ne sont PAS des valeurs de gain reduction FabFilter.)')
        else:
            self.activity_inspector.setText(
                'Activité du signal au seuil : '
                + inspection.get('reason', 'mesure non disponible') + '.')
        rms = metrics.get('rms_dbfs')
        peak = metrics.get('sample_peak_dbfs')
        crest = metrics.get('crest_db')
        parts = ['RMS : ' + str(rms) + ' dBFS', 'Peak : ' + str(peak) + ' dBFS',
                 'Crest : ' + str(crest) + ' dB']
        if self._active[1] != 'original':
            if metrics.get('same_samples_as_original'):
                parts.append('⚠ WAV STRICTEMENT IDENTIQUE À ORIGINAL — vérifier le rendu Pro-C 3 !')
            else:
                parts.append('Diff. RMS : ' + str(metrics.get('rms_delta_db')) + ' dB')
                parts.append('Null RMS : ' + str(metrics.get('null_difference_rms_dbfs')) + ' dBFS')
        if self._active[1] != 'original':
            report = self._reports.get(self._active[0], {})
            plan = report.get('adaptive_plan') or {}
            scenario = (plan.get('scenarios') or {}).get(self._active[1], {})
            if scenario:
                # These are exact normalized plugin points, not physical dB/ratio.
                parts.append('Réglages calibrés : threshold='
                             + str(scenario.get('threshold'))
                             + ', ratio=' + str(scenario.get('ratio'))
                             + ' (normalisés)')
        window = metrics.get('window_analysis', {})
        # Even in Original, show where the recommended compression changes the
        # signal so users can start on Original, jump, then switch Gentle/Firm.
        marker_variant = self._active[1]
        if marker_variant == 'original':
            candidates = ('gentle', 'firm')
            available = [
                (variant, self._diagnostics.get('metrics', {})
                 .get(self._active[0] + '/' + variant, {})
                 .get('window_analysis', {}).get('review_markers', []))
                for variant in candidates
            ]
            marker_variant = next(
                (variant for variant, items in available if items), None)
            if marker_variant:
                window_for_markers = self._diagnostics.get('metrics', {}).get(
                    self._active[0] + '/' + marker_variant, {}).get('window_analysis', {})
            else:
                window_for_markers = {}
        else:
            window_for_markers = window
        self._marker_reference = marker_variant
        self._set_review_markers(window_for_markers.get('review_markers', []))
        if window.get('status') == 'measured':
            parts.append('Passages forts vs calmes : '
                         + str(window['loud_relative_to_quiet_db']) + ' dB (comparaison PCM)')
            if window.get('overcompression_warning'):
                parts.append('⚠ Forte réduction relative des passages forts : écoute les transitoires')
            if window.get('effect_nearly_inaudible_warning'):
                parts.append('Effet très discret dans les fenêtres mesurées')
        self.measure_status.setText('  |  '.join(parts))
        self._update_advisor()


    def set_intensity(self, intensity):
        if intensity not in ('natural','balanced','punchy'):
            return
        self._intensity = intensity
        self._update_intensity_styles()
        self._update_advisor()

    def _update_intensity_styles(self):
        for key, button in self.intensity_buttons.items():
            selected = key == self._intensity
            button.setStyleSheet(
                'QPushButton {background:#282c41;border:2px solid #8f91e8;color:white;font-weight:700;}'
                if selected else
                'QPushButton {background:#171920;border:1px solid #373c46;color:#c7cbd5;}')

    def _update_advisor(self):
        metrics = self._diagnostics.get('metrics', {})
        mix = self._active[0]
        if not metrics:
            self._advisor_choice = 'original'
            self.audition_suggestion.setEnabled(False)
            self.advisor_status.setText('Analyse en attente. La suggestion ne modifie aucun son.')
            return
        result = suggest_compression(metrics, mix, self._intensity)
        fallback_choice = result['variant']
        key = mix + '/' + self._intensity
        record = self._ai_compression.get('choices', {}).get(key, {})
        # Do not trust editable local AI cache (or an LLM response) blindly.
        _scored, allowed = _safe_choice(metrics, self._reports, mix, self._intensity)
        ai_variant = record.get('selected')
        if ai_variant in allowed and self._ai_compression.get('mode') == 'hermes':
            selected, prefix = ai_variant, '🧠 Hermes local'
            explanation = str(record.get('reason', 'Suggestion basée sur les mesures.'))[:160]
        else:
            selected = fallback_choice if fallback_choice in allowed else 'original'
            prefix = '✦ Conseiller PCM'
            explanation = result['reason']
        self._advisor_choice = selected
        self.audition_suggestion.setEnabled((mix, selected) in self._files)
        self.advisor_status.setText(prefix + ' : ' + MIX_NAMES[mix] + ' + '
                                    + COMP_NAMES[selected] + ' · ' + explanation
                                    + ' · Suggestion seulement : ♥ requis pour le mastering.')

    def preview_suggestion(self):
        # An audition never implicitly approves mastering. This button is a
        # convenience selector, not a new playback clock or an AI FX write.
        key = (self._active[0], self._advisor_choice)
        if key in self._files:
            self.select_compression(self._advisor_choice)

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
        self._diagnostics = result.get('diagnostics', {})
        self._ai_compression = result.get('ai_compression', {})
        # Only prepare synchronized playback once all nine immutable copies exist.
        self._setup_players()
        self._refresh_gentle_gate()
        self._update_active_diagnostics()
        self.prepare.setVisible(False)
        diagnostic_note = ' Mesures calculées sur les WAV.' if self._diagnostics else ' ⚠ Diagnostic indisponible : ' + str(result.get('diagnostics_error','erreur non précisée'))
        self.status.setText(('9 combinaisons adaptatives récupérées du cache.' if result.get('cached') else '9 combinaisons préparées avec grille Pro-C 3 adaptée au mix.') + diagnostic_note + ' ♥ approuve pour le mastering.')
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

    def _gentle_is_fallback(self, mix):
        return self._reports.get(mix, {}).get('smart_gentle', {}).get('status') == 'fallback_original'

    def _refresh_gentle_gate(self):
        mix = self._active[0]
        self.hearts['gentle'].setEnabled(
            bool(self._files) and not self._gentle_is_fallback(mix))
        self.buttons['gentle'].setToolTip(
            'Aucun traitement retenu — Original diffusé'
            if self._gentle_is_fallback(mix) else
            'Gentle : meilleur essai Pro-C 3 validé sur cette chanson')

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
        self._refresh_gentle_gate()
        self._select_audible()
        self._update_active_diagnostics()
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
        if comp == 'gentle' and self._gentle_is_fallback(key[0]):
            QMessageBox.information(self, 'Smart Gentle',
                'Aucun essai Gentle retenu. Original reste la source.'
                ' Choisis ♥ Original si tu veux approuver cette version.')
            return
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
        self._diagnostics = {}
        self._approved = None
        self._session_tag = None
        self._sources = {}
        self._active = ('balanced','original')
        self.waveform.setData(None)
        self.file_status.setText('Fichier actif : en attente')
        self.measure_status.setText('Mesures WAV : en attente')
        self.gentle_explanation.setText('Gentle : diagnostic en attente')
        self.smart_gentle_status.setText('Smart Gentle : essais en attente')
        self.activity_inspector.setText('Activité du signal au seuil : en attente')
        self._set_review_markers([])
        self._update_advisor()
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
