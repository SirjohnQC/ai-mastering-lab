"""Guided Auto Studio front end; existing STEM+ and JUCE remain the audio backend.

The streamlined screen deliberately does not pretend premixes are final streaming masters.
"""
from __future__ import annotations
import shutil
import re
import threading
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QStackedWidget, QSlider, QMessageBox,
    QFileDialog, QProgressBar, QCheckBox, QSizePolicy, QScrollArea, QLineEdit, QDialog, QTextEdit, QApplication)
from .mix_comparison import load_comparison, VARIANT_ORDER, VARIANT_LABELS
from .waveform_preview import WaveformStrip, WaveformLoader
from .ui_language import get_language, set_language, tr


class MixCard(QFrame):
    """Compact, intentionally styled card independent of the global QWidget theme."""
    selected = Signal(str)

    ICONS = {'balanced': '≋', 'vocal-focus': '♩', 'punchy': '◉'}

    def __init__(self, key, label, subtitle, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName('mixCard')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(125)
        self.setMaximumHeight(153)
        self.setCursor(Qt.PointingHandCursor)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 18, 12)
        outer.setSpacing(7)
        h = QHBoxLayout()
        h.setSpacing(14)
        outer.addLayout(h)

        self.icon = QLabel(self.ICONS.get(key, '◉'))
        self.icon.setAlignment(Qt.AlignCenter)
        self.icon.setFixedWidth(30)
        self.icon.setStyleSheet('background:transparent;border:none;color:#c9cbd5;font-size:23px;')
        h.addWidget(self.icon)

        labels = QVBoxLayout()
        labels.setSpacing(4)
        self.title = QLabel(label)
        self.title.setStyleSheet('background:transparent;border:none;color:#f6f6fa;font-weight:700;font-size:15px;')
        self.subtitle = QLabel(subtitle)
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet('background:transparent;border:none;color:#a6a9b4;font-size:12px;')
        labels.addWidget(self.title)
        labels.addWidget(self.subtitle)
        h.addLayout(labels, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        right.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.mark = QLabel('')
        self.mark.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.mark.setStyleSheet('background:transparent;border:none;color:#43d692;font-weight:700;font-size:12px;')
        self.lufs = QLabel('— LUFS')
        self.lufs.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lufs.setStyleSheet('background:transparent;border:none;color:#a6a9b4;font-size:11px;')
        right.addWidget(self.mark)
        right.addWidget(self.lufs)
        h.addLayout(right)
        self.ai_pick = QLabel('')
        self.ai_pick.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ai_pick.setStyleSheet('background:transparent;border:none;color:#c2b4ff;font-weight:700;font-size:11px;')
        right.addWidget(self.ai_pick)
        self.waveform = WaveformStrip(self)
        outer.addWidget(self.waveform)
        self.selected_style(False)

    def selected_style(self, selected):
        self.setStyleSheet(
            'QFrame#mixCard { background-color:%s; border:1px solid %s; '
            'border-radius:12px; }' %
            ('#1a1925' if selected else '#17181d', '#7d77ce' if selected else '#373940')
        )
        self.mark.setText('✓  Sélectionné' if selected else '')

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.key)
        super().mousePressEvent(event)


class SingleMixEvaluationWorker(QThread):
    """Evaluate three existing WAVs without blocking the Qt event loop."""
    completed = Signal(str, object, int)

    def __init__(self, report_path, paths, parent=None, *, reference_path=None, preferences_path=None, token=0):
        super().__init__(parent)
        self.report_path = str(Path(report_path).resolve())
        self.reference_path = reference_path
        self.preferences_path = preferences_path
        self.token = token
        self.paths = {key: str(Path(value).resolve()) for key, value in paths.items()}

    def run(self):
        try:
            from .album_mix_evaluation import choose_candidate
            selected, decision = choose_candidate(self.paths, reference_path=self.reference_path, preferences_path=self.preferences_path)
        except Exception as exc:
            selected = 'balanced'
            decision = {'mode': 'fallback', 'selected': 'balanced',
                        'reason': f'{type(exc).__name__}: {exc}'}
        self.completed.emit(self.report_path, decision, self.token)


class AutoMasterWorker(QThread):
    """Runs FFmpeg off the UI thread. Cancellation uses a thread-safe Event."""
    stage = Signal(str, int)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, source, output_dir, parent=None, *, song_title=None, mix_variant=None):
        super().__init__(parent)
        self.source = Path(source)
        self.output_dir = Path(output_dir)
        self.stop_event = threading.Event()
        self.song_title = song_title
        self.mix_variant = mix_variant

    def cancel(self):
        self.stop_event.set()

    def run(self):
        from .auto_master import master_song, MasteringCancelled
        try:
            result = master_song(self.source, self.output_dir,
                stop=self.stop_event,
                progress=lambda description, percent: self.stage.emit(description, percent))
            if self.song_title:
                from .album_export_naming import rename_album_master
                result = rename_album_master(result, self.song_title, self.mix_variant)
            self.completed.emit(result)
        except MasteringCancelled:
            self.failed.emit('Auto Master annulé. Les WAV originaux sont intacts.')
        except Exception as exc:
            self.failed.emit(str(exc))


class ReleasePreflightWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = str(source)

    def run(self):
        try:
            from .release_preflight import run_preflight
            self.completed.emit(run_preflight(self.source))
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class AIFXWorker(QThread):
    """Run local Hermes or offline JUCE without freezing the compare page."""
    completed = Signal(str, object, str)
    failed = Signal(str, str)

    def __init__(self, mode, source, root, *, reference_path=None, eq_preferences_path=None, plan=None, creative=False, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.source = str(Path(source).resolve())
        self.root = str(root)
        self.reference_path = reference_path
        self.eq_preferences_path = eq_preferences_path
        self.plan = plan
        self.creative = creative

    def run(self):
        from .ai_fx_intelligence import propose_for_wav, render_approved_eq
        try:
            if self.mode == 'propose':
                result = propose_for_wav(self.source, reference_path=self.reference_path,
                                         eq_preferences_path=self.eq_preferences_path, creative=self.creative)
            elif self.mode == 'diagnose_compressor':
                from .pro_c3_calibration import inspect_and_save
                result = inspect_and_save(self.root)
            elif self.mode == 'probe_compressor':
                from .pro_c3_multipoint import probe_and_save
                result = probe_and_save(self.root)
            elif self.mode == 'bench_compressor':
                from .pro_c3_testbench import bench_and_save
                result = bench_and_save(self.root)
            elif self.mode == 'validate_compressor_parameters':
                from .pro_c3_parameter_validation import run_validation
                result = run_validation(self.root)
            elif self.mode == 'render':
                result = render_approved_eq(self.source, self.plan, root=self.root)
            else:
                raise ValueError('Opération FX inconnue')
            self.completed.emit(self.mode, result, self.source)
        except Exception as exc:
            self.failed.emit(self.mode, f'{type(exc).__name__}: {exc}')


class AutoStudioPage(QWidget):
    """A single, navigable page for import, production, comparison and handoff."""
    openAdvanced = Signal()
    openMastering = Signal(str)

    def __init__(self, root: Path, stems, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.stems = stems
        self._report = None
        self._selected = 'balanced'
        self._player = None  # Owns sounddevice stream and background analysis, not shown as popup.
        self._current_source = None
        self._analysed = False
        self._last_message = ''
        self._waveform_loader = None
        self._waveform_jobs = []
        self._waveform_token = None
        self._master_worker = None
        self._ai_jobs = []
        self._fx_worker = None
        self._fx_plan = None
        self._fx_source = None
        self._fx_audition = None
        self._fx_render_report = None
        self._fx_ab_player = None
        self._ai_decision = None
        self._ai_token = 0
        self._manual_selected = False
        self._master_result = None
        self._master_completed_key = None
        self._master_running_key = None
        self._master_input = None
        self._master_song_title = None
        self._master_mix_variant = None
        self._master_preview = None
        self._master_audio_output = None
        self._master_waveform_loader = None
        self._master_waveform_jobs = []
        self._master_waveform_token = 0
        self._master_preview_path = None
        self._master_seek_dragging = False
        self._album_page = None
        self._language = get_language()
        self._init_ui()
        stems.audioLoaded.connect(self._audio_loaded)
        stems.productionStatus.connect(self._on_status)
        stems.productionFinished.connect(self._on_ready)
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(170)
        self.ui_timer.timeout.connect(self._sync_player)
        self.ui_timer.start()
        QTimer.singleShot(250, self._restore)
        # Attach the developer tools to the main-window menu once Qt has
        # finished constructing the parent window. Never crowd Simple Mode.
        QTimer.singleShot(0, self._install_calibration_menu)

    def _install_calibration_menu(self):
        host = self.window()
        if host is self or not hasattr(host, 'menuBar'):
            QTimer.singleShot(250, self._install_calibration_menu)
            return
        menu_bar = host.menuBar()
        menu = next((entry.menu() for entry in menu_bar.actions()
                     if entry.menu() is not None and entry.text() == 'Tools'), None)
        if menu is None:
            menu = menu_bar.addMenu('Tools')
        if not any(action.objectName() == 'proC3CalibrationAction' for action in menu.actions()):
            action = menu.addAction('Plugin Calibration — Pro-C 3…')
            action.setObjectName('proC3CalibrationAction')
            action.triggered.connect(self._show_calibration_tools)

    def _set_fx_status(self, message):
        """Update the AI FX status and the detached calibration dialog safely."""
        self.fx_status.setText(message)
        if hasattr(self, '_calibration_status'):
            self._calibration_status.setText(message)

    def _show_calibration_tools(self):
        self._calibration_dialog.show()
        self._calibration_dialog.raise_()
        self._calibration_dialog.activateWindow()

    def _init_ui(self):
        self.setObjectName('autoStudioPage')
        # The desktop theme styles every QWidget. Keep the guided UI inside a
        # centered, width-limited surface and make all text backgrounds transparent.
        self.setStyleSheet("""
            QWidget#autoStudioPage QLabel { background:transparent; border:none; }
            QWidget#autoStudioPage QFrame#mixCard QLabel { background:transparent; border:none; }
            QWidget#autoStudioPage QPushButton#primary {
                background:#7779d9; color:#fff; border-radius:9px;
                font-weight:700; padding:12px 18px;
            }
        """)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.addStretch(1)
        self.content = QWidget(self)
        self.content.setObjectName('autoStudioContent')
        self.content.setMaximumWidth(900)
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(self.content, 10)
        outer.addStretch(1)
        root = QVBoxLayout(self.content)
        root.setContentsMargins(6, 2, 6, 8)
        root.setSpacing(18)
        header = QHBoxLayout()
        name = QLabel('AUTO STUDIO')
        name.setStyleSheet('background:transparent;font-size:20px;font-weight:800;color:#f0efff;')
        header.addWidget(name)
        header.addStretch()
        advanced = QPushButton('⚙  Advanced')
        advanced.setObjectName('secondary')
        advanced.clicked.connect(lambda *_: self.openAdvanced.emit())
        header.addWidget(advanced)
        from PySide6.QtWidgets import QComboBox
        self.language_combo = QComboBox(self)
        self.language_combo.addItem('Français', 'fr')
        self.language_combo.addItem('English', 'en')
        self.language_combo.setCurrentIndex(0 if self._language == 'fr' else 1)
        self.language_combo.currentIndexChanged.connect(self._change_language)
        self.language_combo.setToolTip('Langue / Language')
        header.addWidget(self.language_combo)
        self.advanced_header_button = advanced
        album_button = QPushButton('💿  Album Mode')
        album_button.setObjectName('secondary')
        album_button.clicked.connect(self._open_album)
        header.addWidget(album_button)
        self.album_header_button = album_button
        reference_button = QPushButton('♫  Références')
        reference_button.setObjectName('secondary')
        reference_button.setToolTip('Analyser des fichiers audio et guider Hermes avec un profil de référence local')
        reference_button.clicked.connect(self._open_references)
        header.addWidget(reference_button)
        self.references_header_button = reference_button
        root.addLayout(header)
        subtitle = QLabel('Charge tes stems, lance Auto Produce, compare les 3 mixages et approuve ton choix avant Mastering.')
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet('color:#abb5c8;')
        root.addWidget(subtitle)
        self.subtitle_label = subtitle

        nav = QHBoxLayout()
        self.nav = []
        for i, text in enumerate(('♧  Importer', '✧  Produire', '♫  Comparer', '◎  Mastering')):
            action = QPushButton(text)
            action.setObjectName('autoStudioStep')
            action.setMinimumHeight(44)
            action.setCursor(Qt.PointingHandCursor)
            if i == 0:
                action.clicked.connect(self._show_import)
            elif i == 1:
                action.clicked.connect(self._show_produce)
            elif i == 2:
                action.clicked.connect(self._show_results)
            else:
                action.clicked.connect(self._open_master_stage)
            nav.addWidget(action, 1)
            self.nav.append(action)
        nav.setSpacing(8)
        root.addLayout(nav)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # IMPORT
        intro = QWidget()
        v = QVBoxLayout(intro)
        v.setSpacing(16)
        # The selected-stem list occupies the formerly empty space ABOVE
        # the import controls. Qt gives it the remaining vertical room.
        self.stem_list_heading = QLabel('STEMS SÉLECTIONNÉS')
        self.stem_list_heading.setStyleSheet('background:transparent;color:#b5b9cb;font-size:12px;font-weight:700;')
        self.stem_list_heading.hide()
        v.addWidget(self.stem_list_heading)
        self.stem_list_scroll = QScrollArea()
        self.stem_list_scroll.setObjectName('autoStemList')
        self.stem_list_scroll.setWidgetResizable(True)
        self.stem_list_scroll.setFrameShape(QFrame.NoFrame)
        self.stem_list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stem_list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.stem_list_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.stem_list_scroll.setStyleSheet('QScrollArea#autoStemList { background:transparent; border:none; }')
        self.stem_list_holder = QWidget()
        self.stem_list_holder.setStyleSheet('background:transparent;')
        self.stem_list_layout = QVBoxLayout(self.stem_list_holder)
        self.stem_list_layout.setContentsMargins(0, 0, 4, 0)
        self.stem_list_layout.setSpacing(7)
        self.stem_list_layout.setAlignment(Qt.AlignTop)
        self.stem_list_scroll.setWidget(self.stem_list_holder)
        self.stem_list_scroll.hide()
        v.addWidget(self.stem_list_scroll, 3)
        self._import_top_spacer = v.count()
        v.addStretch(1)
        title = QLabel('Ta musique, ton prochain mix.')
        title.setStyleSheet('font-size:26px;font-weight:750;')
        v.addWidget(title)
        explanation = QLabel('Commence avec les stems d’une chanson. Les fichiers stéréo et albums complets suivront dans un prochain module.')
        explanation.setStyleSheet('color:#abb5c8;')
        explanation.setWordWrap(True)
        v.addWidget(explanation)
        self.song_title_import = QLineEdit()
        self.song_title_import.setObjectName('songTitleImport')
        self.song_title_import.setPlaceholderText(tr(self._language, 'song_title'))
        v.addWidget(self.song_title_import)
        h = QHBoxLayout()
        pick = QPushButton('＋  Choisir des stems')
        pick.setObjectName('primary')
        pick.clicked.connect(self._choose_files)
        folder = QPushButton('▣  Charger un dossier')
        folder.setObjectName('secondary')
        folder.clicked.connect(self._choose_folder)
        h.addWidget(pick)
        h.addWidget(folder)
        self.pick_stems_button = pick
        self.pick_folder_button = folder
        v.addLayout(h)
        self.file_info = QLabel('Aucun stem chargé')
        self.file_info.setStyleSheet('color:#acb5c8;')
        v.addWidget(self.file_info)
        self.produce_btn = QPushButton('✦  AUTO PRODUCE')
        self.produce_btn.setObjectName('primary')
        self.produce_btn.setMinimumHeight(52)
        self.produce_btn.setEnabled(False)
        self.produce_btn.clicked.connect(self._produce)
        v.addWidget(self.produce_btn)
        self.produce_btn.setText(tr(self._language, 'auto_produce'))
        self._import_bottom_spacer = v.count()
        v.addStretch(2)
        self.import_layout = v
        self.stack.addWidget(intro)

        # PRODUCING
        progress = QWidget()
        pv = QVBoxLayout(progress)
        pv.addStretch(1)
        big = QLabel('On s’occupe du mixage. 🎸')
        big.setStyleSheet('font-size:24px;font-weight:700;')
        pv.addWidget(big)
        self.progress_text = QLabel('Préparation…')
        self.progress_text.setWordWrap(True)
        pv.addWidget(self.progress_text)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Honest indeterminate progress.
        pv.addWidget(self.progress)
        pv.addWidget(QLabel('Les stems originaux ne seront pas modifiés.'))
        cancel = QPushButton('Annuler le traitement')
        cancel.setObjectName('secondary')
        cancel.clicked.connect(self.stems._cancel_guided_production)
        pv.addWidget(cancel)
        pv.addStretch(2)
        self.stack.addWidget(progress)

        # RESULTS
        results = QWidget()
        rv = QVBoxLayout(results)
        rv.setContentsMargins(10, 8, 10, 14)
        rv.setSpacing(12)
        header = QLabel('Comparer · Mixage + Compression')
        header.setStyleSheet('background:transparent;font-size:20px;font-weight:750;')
        header.hide()
        rv.addWidget(header)
        summary = QLabel('Choisis celui que tu préfères. La version sélectionnée servira de source pour le mastering.')
        summary.setWordWrap(True)
        summary.setStyleSheet('color:#abb5c8;')
        summary.hide()
        rv.addWidget(summary)
        import_row = QHBoxLayout()
        import_row.addStretch()
        self.change_music = QPushButton('↻  Changer de musique')
        self.change_music.setObjectName('secondary')
        self.change_music.setToolTip('Importer un autre dossier ou une nouvelle sélection de stems')
        self.change_music.clicked.connect(self._show_import)
        import_row.addWidget(self.change_music)
        rv.addLayout(import_row)
        self.cards = {}
        for key, title, desc in (
            ('balanced', 'Balanced', 'Équilibre des stems et réglages de départ'),
            ('vocal-focus', 'Vocal Focus', 'Voix légèrement plus présentes'),
            ('punchy', 'Punchy', 'Drums et basse subtilement renforcés')):
            card = MixCard(key, title, desc, self)
            card.selected.connect(self._user_select)
            card.waveform.clickedPosition.connect(lambda frac, k=key: self._waveform_seek(k, frac))
            self.cards[key] = card
            card.hide()  # Unified studio displays the active mix row instead.
            rv.addWidget(card)
        self.legacy_transport = QWidget(results)
        player_row = QHBoxLayout(self.legacy_transport)
        player_row.setContentsMargins(0, 0, 0, 0)
        self.play = QPushButton('▶  Écouter')
        self.play.clicked.connect(self._toggle_play)
        self.stop = QPushButton('■  Stop')
        self.stop.clicked.connect(self._stop)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 10000)
        self.seek.sliderReleased.connect(self._seek)
        self.clock = QLabel('00:00 / 00:00')
        player_row.addWidget(self.play)
        player_row.addWidget(self.stop)
        player_row.addWidget(self.seek, 1)
        player_row.addWidget(self.clock)
        rv.addSpacing(3)
        self.legacy_transport.hide()
        rv.addWidget(self.legacy_transport)
        self.level = QCheckBox('Comparer à volume égalisé (LUFS)')
        self.level.setEnabled(False)
        self.level.toggled.connect(self._set_level)
        self.level.hide()
        rv.addWidget(self.level)
        # Optional legacy reporting / EQ controls are grouped and collapsed,
        # not deleted. The visible Compare flow remains mix -> compression
        # -> player -> approval -> Mastering.
        self.optional_tools_panel = QFrame(results)
        self.optional_tools_panel.setObjectName('optionalStudioTools')
        self.optional_tools_panel.setStyleSheet(
            'QFrame#optionalStudioTools {background:#171923;border:1px solid #353948;border-radius:10px;}')
        optional_layout = QVBoxLayout(self.optional_tools_panel)
        optional_layout.setContentsMargins(12,12,12,12)
        optional_layout.setSpacing(10)
        self.optional_tools_panel.hide()
        self.analysis_line = QLabel('Analyse en attente…')
        self.analysis_line.setWordWrap(True)
        self.analysis_line.setStyleSheet('color:#aab5ca;')
        optional_layout.addWidget(self.analysis_line)
        self.ai_status = QLabel('Choix IA : en attente de trois mixages…')
        self.ai_status.setWordWrap(True)
        self.ai_status.setStyleSheet('color:#c2b4ff;font-size:12px;')
        optional_layout.addWidget(self.ai_status)
        self.ai_reason = QLabel('')
        self.ai_reason.setWordWrap(True)
        self.ai_reason.setStyleSheet('color:#a6a9b4;font-size:12px;')
        optional_layout.addWidget(self.ai_reason)
        self.ai_use = QPushButton('✦  Utiliser la recommandation IA')
        self.ai_use.setObjectName('secondary')
        self.ai_use.setVisible(False)
        self.ai_use.clicked.connect(self._apply_ai_choice)
        optional_layout.addWidget(self.ai_use)
        pref_row = QHBoxLayout()
        self.pref_save = QPushButton('♡  Mémoriser mon choix')
        self.pref_save.setObjectName('secondary')
        self.pref_save.setEnabled(False)
        self.pref_save.clicked.connect(self._save_preference)
        pref_row.addWidget(self.pref_save)
        self.pref_clear = QPushButton('Effacer mes préférences')
        self.pref_clear.setObjectName('secondary')
        self.pref_clear.clicked.connect(self._clear_preferences_clicked)
        pref_row.addWidget(self.pref_clear)
        optional_layout.addLayout(pref_row)
        self.pref_status = QLabel('Aucun choix confirmé pour cette chanson.')
        self.pref_status.setWordWrap(True)
        self.pref_status.setStyleSheet('background:transparent;color:#a6a9b4;font-size:11px;')
        optional_layout.addWidget(self.pref_status)
        fx_row = QHBoxLayout()
        self.fx_propose = QPushButton('✦  AI FX — essai EQ')
        self.fx_propose.setObjectName('secondary')
        self.fx_propose.setToolTip('Hermes propose un EQ prudent sur le mix choisi, sans application automatique')
        self.fx_propose.clicked.connect(self._propose_ai_fx)
        self.fx_propose.setEnabled(False)
        fx_row.addWidget(self.fx_propose)
        self.fx_listen = QPushButton('♫  Ouvrir l’essai EQ')
        self.fx_listen.setObjectName('secondary')
        self.fx_listen.hide()
        self.fx_listen.clicked.connect(self._open_ai_fx_audition)
        fx_row.addWidget(self.fx_listen)
        optional_layout.addLayout(fx_row)
        # v0.23: one comparison surface: mix cards above, compression choices
        # below, and a nine-stream synchronized player. Old Tools remain
        # strictly advanced and no master is silently compressed.
        from .unified_comparison import UnifiedComparison
        self.unified = UnifiedComparison(self.root, results)
        self.unified.prepared.connect(self._on_unified_prepared)
        self.unified.mixSelected.connect(self._user_select)
        rv.addWidget(self.unified)
        # Legacy separate popup deliberately removed from Simple Mode.
        self.compression_preview = QPushButton('Pro-C 3 intégré')
        self.compression_preview.hide()
        self.compression_preview.setEnabled(False)
        self.fx_status = QLabel('AI FX : choisis un prémix pour demander un essai Pro-Q 4.')
        self.fx_status.setWordWrap(True)
        self.fx_status.setStyleSheet('color:#a6a9b4;font-size:11px;')
        optional_layout.addWidget(self.fx_status)
        self.fx_memory_status = QLabel('🧠 Mémoire EQ : aucune décision confirmée pour le moment.')
        self.fx_memory_status.setWordWrap(True)
        self.fx_memory_status.setStyleSheet('color:#a6a9b4;font-size:11px;')
        optional_layout.addWidget(self.fx_memory_status)
        # Developer-only calibration controls live in a separate Tools dialog.
        # They MUST NOT be added to the simple Compare page.
        self._calibration_dialog = QDialog(self)
        self._calibration_dialog.setWindowTitle('Advanced Tools — Calibration Pro-C 3')
        self._calibration_dialog.setMinimumWidth(520)
        tools_layout = QVBoxLayout(self._calibration_dialog)
        tools_layout.setSpacing(12)
        tools_heading = QLabel('Pro-C 3 — calibration et diagnostics')
        tools_heading.setStyleSheet('background:transparent;font-weight:700;font-size:17px;')
        tools_layout.addWidget(tools_heading)
        tools_note = QLabel('Outils de développement en lecture seule. La compression automatique reste verrouillée tant que les conversions et le comportement audio ne sont pas validés.')
        tools_note.setWordWrap(True)
        tools_note.setStyleSheet('background:transparent;color:#abb5c8;')
        tools_layout.addWidget(tools_note)
        self._calibration_status = QLabel('Prêt pour une inspection sans rendu.')
        self._calibration_status.setWordWrap(True)
        self._calibration_status.setStyleSheet('background:transparent;color:#a8b2ca;')
        # QLabel has no textChanged signal. Mirror updates through an explicit helper.
        # The dialog is not required to be visible for status updates.
        tools_layout.addWidget(self._calibration_status)
        self.fx_pro_c3 = QPushButton('⚙  Calibration Lab Pro-C 3 (lecture seule)')
        self.fx_pro_c3.setObjectName('secondary')
        self.fx_pro_c3.setToolTip('Sauvegarde un rapport de paramètres candidats, sans appliquer de compression')
        self.fx_pro_c3.clicked.connect(self._diagnose_pro_c3)
        tools_layout.addWidget(self.fx_pro_c3)
        self.fx_pro_c3_report = QPushButton('📋  Voir / copier les valeurs Pro-C 3')
        self.fx_pro_c3_report.setObjectName('secondary')
        self.fx_pro_c3_report.setToolTip('Consulter et copier les indices candidats pour la calibration Windows; aucun audio modifié')
        self.fx_pro_c3_report.clicked.connect(self._show_pro_c3_report)
        tools_layout.addWidget(self.fx_pro_c3_report)
        self.fx_pro_c3_probe = QPushButton('🔬  Grille multipoint Pro-C 3 (lecture seule)')
        self.fx_pro_c3_probe.setObjectName('secondary')
        self.fx_pro_c3_probe.clicked.connect(self._probe_pro_c3)
        tools_layout.addWidget(self.fx_pro_c3_probe)
        self.fx_pro_c3_probe_report = QPushButton('📋  Voir / copier la grille multipoint')
        self.fx_pro_c3_probe_report.setObjectName('secondary')
        self.fx_pro_c3_probe_report.clicked.connect(self._show_pro_c3_probe_report)
        tools_layout.addWidget(self.fx_pro_c3_probe_report)
        self.fx_pro_c3_bench = QPushButton('🧪  Test Bench Pro-C 3 — signal synthétique')
        self.fx_pro_c3_bench.setObjectName('secondary')
        self.fx_pro_c3_bench.setToolTip('Rendu sur signal créé automatiquement; ne touche jamais aux chansons')
        self.fx_pro_c3_bench.clicked.connect(self._bench_pro_c3)
        tools_layout.addWidget(self.fx_pro_c3_bench)
        self.fx_pro_c3_bench_report = QPushButton('📋  Voir / copier le dernier test Pro-C 3')
        self.fx_pro_c3_bench_report.setObjectName('secondary')
        self.fx_pro_c3_bench_report.clicked.connect(self._show_pro_c3_bench_report)
        tools_layout.addWidget(self.fx_pro_c3_bench_report)
        self.fx_pro_c3_validate = QPushButton('🧬  Valider les paramètres Pro-C 3 — signal synthétique')
        self.fx_pro_c3_validate.setObjectName('secondary')
        self.fx_pro_c3_validate.clicked.connect(self._validate_pro_c3_parameters)
        tools_layout.addWidget(self.fx_pro_c3_validate)
        self.fx_pro_c3_validate_report = QPushButton('📋  Voir / copier la validation Pro-C 3')
        self.fx_pro_c3_validate_report.setObjectName('secondary')
        self.fx_pro_c3_validate_report.clicked.connect(self._show_pro_c3_validation_report)
        tools_layout.addWidget(self.fx_pro_c3_validate_report)
        self.fx_pro_c3_audition = QPushButton('♫  Écouter A/B/C — synthétique (Original / Gentle / Firm)')
        self.fx_pro_c3_audition.setObjectName('secondary')
        self.fx_pro_c3_audition.setToolTip('Écoute isolée des WAV synthétiques déjà validés; jamais tes chansons')
        self.fx_pro_c3_audition.clicked.connect(self._audition_pro_c3)
        tools_layout.addWidget(self.fx_pro_c3_audition)
        self.fx_pro_c3_song_audition = QPushButton('🎧  Essai A/B/C sur COPIE de mix — manuel, expérimental')
        self.fx_pro_c3_song_audition.setObjectName('secondary')
        self.fx_pro_c3_song_audition.setToolTip('Choisir un WAV et créer des copies temporaires; aucune compression automatique')
        self.fx_pro_c3_song_audition.clicked.connect(self._audition_pro_c3_song)
        tools_layout.addWidget(self.fx_pro_c3_song_audition)
        close_calibration = QPushButton('Fermer les outils')
        close_calibration.setObjectName('secondary')
        close_calibration.clicked.connect(self._calibration_dialog.hide)
        tools_layout.addWidget(close_calibration)
        self.fx_creative = QPushButton('✧  Demander un essai créatif facultatif')
        self.fx_creative.setObjectName('secondary')
        self.fx_creative.hide()
        self.fx_creative.clicked.connect(lambda: self._propose_ai_fx(creative=True))
        optional_layout.addWidget(self.fx_creative)
        from .ai_fx_player import AIFXABPlayer
        self._fx_ab_player = AIFXABPlayer(results, on_play=self._fx_stop_main_audio)
        optional_layout.addWidget(self._fx_ab_player)
        self.fx_feedback_row = QWidget()
        feedback = QHBoxLayout(self.fx_feedback_row)
        feedback.setContentsMargins(0, 0, 0, 0)
        self.fx_prefer_before = QPushButton('♡  Je préfère Avant')
        self.fx_prefer_after = QPushButton('♡  Je préfère Après')
        for button, choice in ((self.fx_prefer_before, 'before'), (self.fx_prefer_after, 'after')):
            button.setObjectName('secondary')
            button.clicked.connect(lambda checked=False, c=choice: self._record_fx_preference(c))
            feedback.addWidget(button)
        self.fx_feedback_row.hide()
        optional_layout.addWidget(self.fx_feedback_row)
        self.fx_feedback_status = QLabel('')
        self.fx_feedback_status.setWordWrap(True)
        optional_layout.addWidget(self.fx_feedback_status)
        rv.addSpacing(8)
        self.continue_btn = QPushButton('→  Continuer vers Mastering — Balanced')
        self.continue_btn.setObjectName('primary')
        self.continue_btn.setMinimumHeight(50)
        self.continue_btn.clicked.connect(self._continue_mastering)
        rv.addWidget(self.continue_btn)
        self.optional_tools_button = QPushButton('⚙ Options facultatives · Advanced (afficher)')
        self.optional_tools_button.setObjectName('secondary')
        self.optional_tools_button.clicked.connect(self._toggle_optional_tools)
        rv.addWidget(self.optional_tools_button)
        rv.addWidget(self.optional_tools_panel)
        self._select('balanced')
        self._apply_language()
        secondary = QHBoxLayout()
        self.gen2 = QPushButton('✦  Améliorer avec Gen 2')
        self.gen2.setObjectName('secondary')
        self.gen2.clicked.connect(self._generate_next)
        more = QPushButton('Retouches Advanced')
        more.setObjectName('secondary')
        more.clicked.connect(lambda *_: self.openAdvanced.emit())
        details = QPushButton('Rapport & spectrogrammes')
        details.setObjectName('secondary')
        details.clicked.connect(self._show_details)
        self.more_button = more
        self.details_button = details
        secondary.addWidget(self.gen2, 1)
        secondary.addWidget(more, 1)
        secondary.addWidget(details, 1)
        rv.addLayout(secondary)
        disclaimer = QLabel('Ces trois fichiers sont des prémix, pas encore des masters certifiés pour la distribution.')
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet('color:#9faac0;font-size:12px;')
        rv.addWidget(disclaimer)
        self.disclaimer_label = disclaimer
        rv.addStretch(1)
        result_scroll = QScrollArea()
        result_scroll.setWidgetResizable(True)
        result_scroll.setFrameShape(QFrame.NoFrame)
        result_scroll.setWidget(results)
        self.stack.addWidget(result_scroll)

        # MASTERING — one deliberate action, progress, QC and downloadable output.
        master = QWidget()
        ml = QVBoxLayout(master)
        ml.setContentsMargins(12, 20, 12, 20)
        ml.setSpacing(17)
        ml.addStretch(1)
        mt = QLabel('Ton mix, ton master.')
        mt.setStyleSheet('background:transparent;font-size:24px;font-weight:750;')
        ml.addWidget(mt)
        self.master_headline = mt
        self.master_description = QLabel('Sélectionne un mixage sur la page Comparer pour commencer.')
        self.master_description.setWordWrap(True)
        self.master_description.setStyleSheet('color:#abb5c8;')
        ml.addWidget(self.master_description)
        self.master_title_label = QLabel('Nom de la chanson (nom du fichier exporté)')
        ml.addWidget(self.master_title_label)
        self.song_title_master = QLineEdit()
        self.song_title_master.setObjectName('songTitleMaster')
        self.song_title_master.setPlaceholderText('Ex. All We Know Is Falling')
        ml.addWidget(self.song_title_master)
        self.song_title_import.textChanged.connect(self._sync_title_from_import)
        self.song_title_master.textChanged.connect(self._sync_title_from_master)
        self.master_progress = QProgressBar()
        self.master_progress.setRange(0, 100)
        self.master_progress.setValue(0)
        ml.addWidget(self.master_progress)
        self.master_status = QLabel('En attente d’un mixage…')
        self.master_status.setWordWrap(True)
        ml.addWidget(self.master_status)
        self.master_run = QPushButton('✦  AUTO MASTER')
        self.master_run.setObjectName('primary')
        self.master_run.setMinimumHeight(52)
        self.master_run.clicked.connect(self._start_master)
        self.master_run.setEnabled(False)
        ml.addWidget(self.master_run)
        self.master_cancel = QPushButton('Annuler Auto Master')
        self.master_cancel.setObjectName('secondary')
        self.master_cancel.clicked.connect(self._cancel_master)
        self.master_cancel.hide()
        ml.addWidget(self.master_cancel)
        self.master_report = QLabel('')
        self.master_report.setWordWrap(True)
        self.master_report.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.master_report.setStyleSheet('color:#c5c9db;')
        ml.addWidget(self.master_report)
        # Review player: non-destructive waveform, actual Qt playback state,
        # seek controls and transport. Never starts playback automatically.
        self.master_player_panel = QFrame()
        self.master_player_panel.setObjectName('masterReviewPanel')
        self.master_player_panel.setStyleSheet(
            'QFrame#masterReviewPanel { background:#181922; border:1px solid #35374a; '
            'border-radius:10px; }')
        player_layout = QVBoxLayout(self.master_player_panel)
        player_layout.setContentsMargins(14, 12, 14, 12)
        player_layout.setSpacing(9)
        player_title = QLabel('Écoute du master')
        player_title.setStyleSheet('font-size:14px;font-weight:700;color:#f3f2fa;')
        player_layout.addWidget(player_title)
        self.master_review_label = player_title
        self.master_waveform = WaveformStrip(self.master_player_panel)
        self.master_waveform.setFixedHeight(70)
        self.master_waveform.setActive(True)
        self.master_waveform.setToolTip('Clique sur la forme d’onde pour te déplacer dans la chanson')
        self.master_waveform.clickedPosition.connect(self._master_seek_waveform)
        player_layout.addWidget(self.master_waveform)
        transport = QHBoxLayout()
        self.master_listen = QPushButton('▶  Play')
        self.master_listen.setObjectName('secondary')
        self.master_listen.clicked.connect(self._listen_master)
        transport.addWidget(self.master_listen)
        self.master_stop = QPushButton('■  Stop')
        self.master_stop.setObjectName('secondary')
        self.master_stop.clicked.connect(self._stop_master_preview)
        transport.addWidget(self.master_stop)
        self.master_seek = QSlider(Qt.Horizontal)
        self.master_seek.setRange(0, 1000)
        self.master_seek.sliderPressed.connect(self._master_seek_pressed)
        self.master_seek.sliderReleased.connect(self._master_seek_released)
        transport.addWidget(self.master_seek, 1)
        self.master_clock = QLabel('00:00 / 00:00')
        self.master_clock.setMinimumWidth(100)
        self.master_clock.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        transport.addWidget(self.master_clock)
        player_layout.addLayout(transport)
        self.master_player_panel.hide()
        ml.addWidget(self.master_player_panel)
        self.master_open = QPushButton('📁  Ouvrir le fichier master')
        self.master_open.setObjectName('secondary')
        self.master_open.clicked.connect(self._open_master_file)
        self.master_open.hide()
        ml.addWidget(self.master_open)
        self.master_preflight = QPushButton('✓  Vérifier avant publication')
        self.master_preflight.setObjectName('secondary')
        self.master_preflight.setToolTip('Analyse indépendante du WAV exporté, sans modifier le son.')
        self.master_preflight.clicked.connect(self._run_release_preflight)
        self.master_preflight.hide()
        ml.addWidget(self.master_preflight)
        self.master_preflight_status = QLabel('')
        self.master_preflight_status.setWordWrap(True)
        self.master_preflight_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ml.addWidget(self.master_preflight_status)
        self._preflight_worker = None
        advanced_master = QPushButton('Réglages avancés et références →')
        advanced_master.setObjectName('secondary')
        advanced_master.clicked.connect(self._handoff_to_advanced_master)
        ml.addWidget(advanced_master)
        self.master_advanced_button = advanced_master
        caution = QLabel('Première passe technique : loudness, true peak et WAV 24-bit. '
                         'Les contrôles QC ne remplacent pas l’écoute humaine ni la cohérence d’un album complet.')
        caution.setWordWrap(True)
        caution.setStyleSheet('color:#a0aabb;font-size:12px;')
        ml.addWidget(caution)
        ml.addStretch(2)
        self.stack.addWidget(master)
        self._apply_language()
        self._go(0)

    def _change_language(self, index):
        language = self.language_combo.itemData(index)
        if language not in ('fr', 'en'):
            return
        self._language = language
        set_language(language)
        self._apply_language()

    def _apply_language(self):
        """Translate main Auto Studio controls without restarting audio."""
        lang = self._language
        self.advanced_header_button.setText(tr(lang, 'advanced'))
        self.album_header_button.setText(tr(lang, 'album'))
        self.references_header_button.setText(tr(lang, 'references'))
        self.subtitle_label.setText(tr(lang, 'intro'))
        for i, key in enumerate(('import','produce','compare','master')):
            self.nav[i].setText(tr(lang, key))
        self.pick_stems_button.setText(tr(lang,'pick_stems'))
        self.pick_folder_button.setText(tr(lang,'pick_folder'))
        self.song_title_import.setPlaceholderText(tr(lang,'song_title'))
        self.produce_btn.setText(tr(lang,'auto_produce'))
        self.change_music.setText(tr(lang,'change_music'))
        self.continue_btn.setText(tr(lang,'continue',mix=VARIANT_LABELS.get(self._selected, 'Balanced')))
        self.optional_tools_button.setText(tr(
            lang,'options_open' if self.optional_tools_panel.isVisible()
            else 'options_closed'))
        self.unified.set_language(lang)
        if hasattr(self, 'master_headline'):
            self.master_headline.setText(tr(lang,'master_headline'))
            self.master_title_label.setText(tr(lang,'master_title'))
            self.master_review_label.setText(tr(lang,'master_review'))
            self.master_cancel.setText(tr(lang,'master_cancel'))
            self.master_open.setText(tr(lang,'master_open'))
            self.master_preflight.setText(tr(lang,'master_preflight'))
            self.master_advanced_button.setText(tr(lang,'master_advanced'))
            self.gen2.setText(tr(lang,'gen2'))
            self.more_button.setText(tr(lang,'more'))
            self.details_button.setText(tr(lang,'details'))
            self.disclaimer_label.setText(tr(lang,'disclaimer'))
            if self._master_input is None:
                self.master_description.setText(tr(lang,'master_initial'))
            else:
                self.master_description.setText(tr(lang,'source',name=self._master_input.name,
                                                   variant=self._master_mix_variant or 'original'))
        self._update_master_button()

    def _toggle_optional_tools(self):
        show = not self.optional_tools_panel.isVisible()
        self.optional_tools_panel.setVisible(show)
        self.optional_tools_button.setText(tr(
            self._language, 'options_open' if show else 'options_closed'))

    def _open_references(self):
        if not self._can_change_music():
            return
        from .reference_learning_ui import ReferenceLibraryDialog
        dialog = ReferenceLibraryDialog(self.root, self)
        dialog.exec()
        if self._report and self._player and self.stack.currentIndex() == 2:
            # Re-evaluate existing three mixes after reference changes.
            self._clear_ai_decision()
            self._start_ai_evaluation(self._player.paths)

    def _open_album(self):
        if not self._can_change_music():
            return
        if self._fx_ab_player is not None:
            self._fx_ab_player.stop()
        if self._album_page is None:
            from .album_studio_ui import AlbumStudioPage
            self._album_page = AlbumStudioPage(self.root, self)
            self.stack.addWidget(self._album_page)
        self.stack.setCurrentWidget(self._album_page)
        for button in self.nav:
            button.setStyleSheet('')

    def _go(self, index):
        if index == 2 and hasattr(self, 'unified'):
            QTimer.singleShot(0, self._start_cached_compare)
        if index != 2 and hasattr(self, 'unified'):
            self.unified.stop()
        if index != 2 and self._fx_ab_player is not None:
            self._fx_ab_player.stop()
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.nav):
            chosen = i == min(index, 3)
            button.setStyleSheet(
                'QPushButton { background:%s;border:1px solid %s;border-radius:8px;'
                'color:%s;font-weight:%s;padding:8px; }'
                'QPushButton:hover { background:#292b3e; }' % (
                    '#292741' if chosen else '#191b24',
                    '#68629d' if chosen else '#303340',
                    '#f5f4ff' if chosen else '#a0aab9',
                    '700' if chosen else '400'))

    def _start_cached_compare(self):
        if self.stack.currentIndex() != 2 or not hasattr(self, 'unified'):
            return
        if len(self.unified._sources) != 3 or self.unified._files or self.unified.is_busy():
            return
        if self._player is not None:
            self._player.stop()
        self.unified.prepare_automatically()

    def _can_change_music(self):
        if hasattr(self, 'unified') and self.unified.is_busy():
            QMessageBox.information(self, 'Compression en cours', 'Attends la fin des six rendus JUCE.')
            return False
        if self._master_worker is not None and self._master_worker.isRunning():
            QMessageBox.information(self, 'Mastering en cours', 'Annule Auto Master avant de changer de musique.')
            return False
        if self.stack.currentIndex() == 1 or bool(getattr(self.stems, '_guided_pipeline', False)):
            QMessageBox.information(self, 'Traitement en cours',
                'Attends la fin du traitement ou utilise Annuler avant de changer de musique.')
            return False
        if self._player_busy():
            QMessageBox.information(self, 'Analyse en cours',
                'Attends la fin de l’analyse avant de changer de musique.')
            return False
        return True

    def _show_import(self):
        if self._can_change_music():
            self._go(0)

    def _show_produce(self):
        if self._can_change_music():
            self._go(0)  # Auto Produce lives on the import screen.
            if self.stems.rows:
                self.produce_btn.setFocus()

    def _show_results(self):
        if self._report and self._player:
            self._go(2)
        else:
            self._go(0)

    def _choose_files(self):
        if self._can_change_music():
            self.stems.choose_files()

    def _choose_folder(self):
        if self._can_change_music():
            self.stems.browse()

    def _refresh_stem_list(self):
        # Rebuild only the small import view; STEM+ owns the actual project state.
        while self.stem_list_layout.count():
            item = self.stem_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        current = self.stems.states() if self.stems.rows else []
        has_files = bool(current)
        self.stem_list_scroll.setVisible(has_files)
        self.stem_list_heading.setVisible(has_files)
        # When empty, vertically center the import form. Once populated,
        # dedicate that unused space to the scrollable file list instead.
        self.import_layout.setStretch(self._import_top_spacer, 0 if has_files else 1)
        self.import_layout.setStretch(self._import_bottom_spacer, 0 if has_files else 2)
        for entry in current:
            file_path = str(entry['file'])
            line = QFrame(self.stem_list_holder)
            line.setStyleSheet('QFrame { background:#1b1e2b; border:1px solid #34384b; border-radius:7px; }')
            horizontal = QHBoxLayout(line)
            horizontal.setContentsMargins(10, 5, 6, 5)
            horizontal.setSpacing(8)
            name = QLabel('♫  ' + Path(file_path).name)
            name.setToolTip(file_path)
            name.setStyleSheet('background:transparent;border:none;color:#e8e9f1;font-size:12px;')
            horizontal.addWidget(name, 1)
            remove = QPushButton('×')
            remove.setToolTip('Retirer de ce projet (sans effacer le fichier audio)')
            remove.setAccessibleName('Retirer ' + Path(file_path).name)
            remove.setFixedSize(30, 26)
            remove.setStyleSheet('QPushButton { background:#2b3041;color:#e0e3ef;border:1px solid #42485a;border-radius:5px;font-size:17px; } QPushButton:hover { background:#642f3d;color:white; }')
            remove.clicked.connect(lambda checked=False, f=file_path: self._remove_stem(f))
            horizontal.addWidget(remove)
            self.stem_list_layout.addWidget(line)

    def _remove_stem(self, file_path):
        if not self._can_change_music():
            return
        try:
            self.stems.remove_stem_from_selection(file_path)
        except Exception as exc:
            QMessageBox.warning(self, 'Retrait du stem impossible', str(exc))

    def _audio_loaded(self, count, label):
        if hasattr(self, 'unified') and not self.unified.is_busy():
            self.unified.reset()
            self.legacy_transport.hide()
            self.level.hide()
        # Called only after successful loading. Cancelling the file picker does
        # not emit audioLoaded, so the existing results remain available.
        self._invalidate_waveforms()
        self._close_player()
        self._clear_ai_decision()
        self._reset_ai_fx()
        self._report = None
        self._current_source = None
        self._master_input = None
        self._master_song_title = None
        self._master_mix_variant = None
        self._master_result = None
        self._master_completed_key = None
        self._master_running_key = None
        self.song_title_import.setText(self._inferred_title_from_stems() or '')
        self._reset_master_preview()
        self.master_run.setEnabled(False)
        self.master_open.hide()
        self.master_progress.setValue(0)
        self.master_report.setText('')
        self._analysed = False
        self.analysis_line.setText('Analyse en attente…')
        self.level.blockSignals(True)
        self.level.setChecked(False)
        self.level.setEnabled(False)
        self.level.blockSignals(False)
        for card in self.cards.values():
            card.lufs.setText('— LUFS')
        self.gen2.setVisible(True)
        self._select('balanced')
        self.file_info.setText(f'✓  {count} stems chargés  ·  {label}' if count else 'Aucun stem chargé')
        self._refresh_stem_list()
        self.produce_btn.setEnabled(count > 0)
        self._go(0)

    def _restore(self):
        if self.stems.rows:
            self._audio_loaded(len(self.stems.rows), Path(self.stems.folder.text()).name)
        report = self.stems._find_comparison_report()
        if report and report.is_file():
            self._on_ready(str(report), analyze=False)

    def _produce(self):
        if not self.stems.rows:
            QMessageBox.information(self, 'Aucun audio', 'Choisis des stems pour commencer.')
            return
        if self._player and self._player_busy():
            QMessageBox.information(self, 'Analyse en cours',
                'Attends la fin de l’analyse précédente avant de redémarrer Auto Produce.')
            return
        self._close_player()
        self._go(1)
        self.progress_text.setText('Analyse des stems et préparation des FX…')
        self.stems.start_guided_production()
        if not self.stems._guided_pipeline and self.stems.job.state() == self.stems.job.NotRunning:
            self._go(0)

    def _on_status(self, text):
        self.progress_text.setText(text)
        if text.startswith('Auto Produce annulé') or text.startswith('Auto Produce arrêté'):
            self._go(0)

    def _player_busy(self):
        p = self._player
        return bool(p and any(getattr(p, key, None) is not None for key in
            ('_evaluation_thread', '_loudness_thread', '_gen2_thread', '_eq_thread', '_eq_audition_thread')))

    def _on_ready(self, report, analyze=True):
        from .mix_compare_ui import MixCompareDialog
        try:
            paths, _spec = load_comparison(report)
            self._invalidate_waveforms()
            if self.unified.is_busy():
                raise RuntimeError('Termine la préparation Pro-C 3 avant de changer la session.')
            self.unified.reset()
            self.legacy_transport.hide()
            self.level.hide()
            self._close_player()
            self._clear_ai_decision()
            self._reset_ai_fx()
            # Reuse the tested synchronized audio/analysis engine, keep its verbose
            # UI hidden behind the optional "Rapport & spectrogrammes" action.
            self._player = MixCompareDialog(Path(report), self)
            self.unified.set_sources(self._player.paths, session_tag=str(Path(report).resolve()))
            self._current_source = str(Path(report).resolve())
            self._report = Path(report)
            self._analysed = False
            self.analysis_line.setText('DSP, Hermes et LUFS en cours…' if analyze else 'Session précédente chargée. Rapports accessibles dans « Rapport & spectrogrammes ».')
            self.level.setEnabled(False)
            self.level.setChecked(False)
            for card in self.cards.values():
                card.lufs.setText('— LUFS')
            self._select('balanced')
            self._go(2)
            self._load_waveforms(paths)
            self.fx_propose.setEnabled(True)
            self._start_ai_evaluation(paths)
            self._player.automaticAnalysisFinished.connect(self._analysis_complete)
            self._player._generation_result_label.setText('Nouvelle génération prête — analyse automatique en cours…')
            if analyze:
                QTimer.singleShot(120, self._player.start_automatic_analysis)
            self.gen2.setVisible(not self._report_is_gen2())
        except Exception as exc:
            self._go(0)
            QMessageBox.warning(self, 'Comparaison impossible', str(exc))

    def _report_is_gen2(self):
        try:
            import json
            return bool(json.loads(self._report.read_text(encoding='utf-8')).get('parent_comparison'))
        except Exception:
            return False

    def _analysis_complete(self, ok, explanation):
        self._analysed = True
        self.analysis_line.setText(('✓  Analyse terminée. ' if ok else '⚠  Analyse partielle. ') + str(explanation))
        if self._player:
            text = self._player._match_status.text()
            for key in VARIANT_ORDER:
                match = re.search(re.escape(VARIANT_LABELS[key]) + r'\s+(-?\d+(?:\.\d+)?)\s*LUFS', text)
                if match:
                    self.cards[key].lufs.setText(match.group(1) + ' LUFS')
        self.level.setEnabled(bool(self._player and self._player._match_check.isEnabled()))
        if self._player and self._player._loudness_matched:
            self.level.setChecked(True)

    def _clear_ai_decision(self):
        self._ai_token += 1
        self._ai_decision = None
        self._manual_selected = False
        self.ai_status.setText('Choix IA : en attente de trois mixages…')
        self.ai_reason.clear()
        self.ai_use.hide()
        self.pref_save.setEnabled(False)
        self.pref_status.setText('Aucun choix confirmé pour cette chanson.')
        for card in self.cards.values():
            card.ai_pick.clear()

    def _start_ai_evaluation(self, paths):
        """Evaluate in a worker; stale results are discarded after re-import/Gen2."""
        if not self._report:
            return
        from .reference_learning import library_path
        from .preference_learning import preference_path
        self._ai_token += 1
        worker = SingleMixEvaluationWorker(self._report, paths, self,
                                           reference_path=library_path(self.root),
                                           preferences_path=preference_path(self.root), token=self._ai_token)
        self._ai_jobs.append(worker)
        self.ai_status.setText('🧠  Hermes évalue Balanced, Vocal Focus et Punchy…')
        worker.completed.connect(self._ai_evaluation_ready)
        worker.finished.connect(lambda w=worker: self._ai_worker_finished(w))
        worker.start()

    def _ai_worker_finished(self, worker):
        if worker in self._ai_jobs:
            self._ai_jobs.remove(worker)
        worker.deleteLater()

    def _ai_evaluation_ready(self, report_path, decision, token):
        if token != self._ai_token or not self._report or str(self._report.resolve()) != report_path:
            return
        self._ai_decision = decision
        selected = decision.get('selected', 'balanced')
        if selected not in self.cards:
            return
        successful = decision.get('mode') == 'hermes'
        title = ('✦  Choix IA : ' if successful else '⚠  Choix secours : ') + VARIANT_LABELS[selected]
        self.ai_status.setText(title)
        reason = str(decision.get('reason', ''))
        if decision.get('reference_used'):
            reason += '\n♫ Profil de références actif pour cette recommandation.'
        if decision.get('preferences_used'):
            reason += '\n♡ Préférences confirmées prises en compte (signal faible).'
        self.ai_reason.setText(reason)
        self.unified.recommended_mix(selected, bool(decision.get('reference_used')))
        self.cards[selected].ai_pick.setText('✦  IA recommande' if successful else '⚠  Secours')
        self.ai_use.setVisible(successful and self._selected != selected)
        self.pref_save.setEnabled(isinstance(decision.get('metrics'), dict))
        # Auto-select the AI recommendation unless the user already chose manually.
        if successful and not self._manual_selected:
            self._select(selected)

    def _user_select(self, key):
        self._manual_selected = True
        self._select(key)

    def _apply_ai_choice(self):
        if self._ai_decision and self._ai_decision.get('mode') == 'hermes':
            self._manual_selected = True
            self._select(self._ai_decision['selected'])

    def _reset_ai_fx(self):
        self._fx_plan = None
        self._fx_source = None
        self._fx_audition = None
        self._fx_render_report = None
        if self._fx_ab_player is not None:
            self._fx_ab_player.reset()
        self.fx_feedback_row.hide()
        self.fx_prefer_before.setEnabled(True)
        self.fx_prefer_after.setEnabled(True)
        self.fx_creative.hide()
        self.fx_feedback_status.setText('')
        self.fx_listen.hide()
        self.fx_propose.setEnabled(bool(self._player and not self._fx_worker))
        self._set_fx_status('AI FX : essai EQ facultatif sur le mix sélectionné. Aucun traitement appliqué.')
        self.fx_memory_status.setText('🧠 Mémoire EQ : analyse non lancée.')

    def _propose_ai_fx(self, *, creative=False):
        if not self._player or self._fx_worker:
            return
        from .reference_learning import library_path
        source = str(Path(self._player.paths[self._selected]).resolve())
        self._fx_plan = None
        self._fx_source = source
        self._reset_ai_fx()
        self._fx_source = source
        self.fx_propose.setEnabled(False)
        self._set_fx_status('🧠 Hermes prépare un essai EQ facultatif…')
        worker = AIFXWorker('propose', source, self.root,
                             reference_path=library_path(self.root),
                             eq_preferences_path=self.root / 'settings' / 'eq_preferences.json',
                             creative=creative, parent=self)
        self._start_fx_worker(worker)

    def _diagnose_pro_c3(self):
        if self._fx_worker:
            return
        self.fx_pro_c3.setEnabled(False)
        self._set_fx_status('Inspection JUCE Pro-C 3 et préparation du rapport en cours…')
        source = str(Path(self._player.paths[self._selected]).resolve()) if self._player else ''
        self._start_fx_worker(AIFXWorker('diagnose_compressor', source or str(self.root), self.root, parent=self))

    def _probe_pro_c3(self):
        if self._fx_worker:
            return
        self.fx_pro_c3_probe.setEnabled(False)
        self._set_fx_status('Lecture multipoint Pro-C 3 en cours… (sans rendu)')
        self._start_fx_worker(AIFXWorker('probe_compressor', str(self.root), self.root, parent=self))

    def _bench_pro_c3(self):
        if self._fx_worker:
            return
        answer = QMessageBox.question(
            self, 'Test Bench Pro-C 3',
            'Créer un signal de test synthétique et le traiter avec Pro-C 3 ?\n\n'
            'Aucune chanson ne sera utilisée ou modifiée. La compression automatique restera verrouillée.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.fx_pro_c3_bench.setEnabled(False)
        self._set_fx_status('Test Bench Pro-C 3 : génération et rendu synthétique en cours…')
        self._start_fx_worker(AIFXWorker('bench_compressor', str(self.root), self.root, parent=self))

    def _validate_pro_c3_parameters(self):
        if self._fx_worker:
            return
        answer = QMessageBox.question(
            self, 'Validation Pro-C 3',
            'Tester DEUX réglages exacts de la grille Pro-C 3 sur un signal synthétique ?\n\n'
            'Aucune chanson ou master ne sera modifié. La compression automatique restera verrouillée.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.fx_pro_c3_validate.setEnabled(False)
        self._set_fx_status('Validation des réglages Pro-C 3 en cours — signal synthétique…')
        self._start_fx_worker(AIFXWorker('validate_compressor_parameters', str(self.root), self.root, parent=self))

    def _audition_pro_c3(self):
        if self._fx_worker:
            QMessageBox.information(self, 'Pro-C 3', 'Un diagnostic est en cours. Réessaie après son rapport.')
            return
        try:
            from .pro_c3_audition import ProC3AuditionDialog
            # Prevent concurrent playback of a real song while diagnosing synthetic audio.
            if self._player:
                self._player.stop()
            if self._fx_ab_player is not None:
                self._fx_ab_player.stop()
            if self._master_preview is not None:
                self._master_preview.stop()
            dialog = ProC3AuditionDialog(self.root, self)
            dialog.exec()
        except Exception as exc:
            QMessageBox.warning(self, 'Écoute Pro-C 3 indisponible', f'{type(exc).__name__}: {exc}')

    def _open_selected_compression_preview(self):
        # This is an explicit opt-in preview. No processing or changes to
        # the master happen merely by selecting a mix or opening this dialog.
        if self._fx_worker or (self._master_worker is not None and self._master_worker.isRunning()):
            QMessageBox.information(self, 'Traitement en cours', 'Termine le traitement en cours avant la préécoute.')
            return
        source = self._selected_mix_path()
        if source is None:
            QMessageBox.information(self, 'Mix manquant', 'Choisis un prémix valide dans Comparer.')
            return
        try:
            from .pro_c3_song_preview_ui import SongCompressionPreviewDialog
            self._stop()
            if self._fx_ab_player is not None:
                self._fx_ab_player.stop()
            if self._master_preview is not None:
                self._master_preview.stop()
            decision = self._ai_decision if isinstance(self._ai_decision, dict) else {}
            context = {
                'selected_mix': VARIANT_LABELS.get(self._selected, self._selected),
                'hermes_mix_choice': VARIANT_LABELS.get(decision.get('selected'), '?'),
                'hermes_mode': decision.get('mode'),
                'reference_used': bool(decision.get('reference_used')),
            }
            dialog = SongCompressionPreviewDialog(self.root, self, initial_source=source,
                                                   studio_context=context)
            try:
                dialog.exec()
            finally:
                dialog._shutdown_audio()
        except Exception as exc:
            QMessageBox.warning(self, 'Préécoute Pro-C 3 indisponible', f'{type(exc).__name__}: {exc}')

    def _audition_pro_c3_song(self):
        if self._fx_worker:
            QMessageBox.information(self, 'Pro-C 3', 'Un autre diagnostic est en cours.')
            return
        try:
            from .pro_c3_song_preview_ui import SongCompressionPreviewDialog
            if self._player: self._player.stop()
            if self._fx_ab_player is not None: self._fx_ab_player.stop()
            if self._master_preview is not None: self._master_preview.stop()
            dialog = SongCompressionPreviewDialog(self.root, self)
            try:
                dialog.exec()
            finally:
                dialog._shutdown_audio()
        except Exception as exc:
            QMessageBox.warning(self, 'Écoute expérimentale impossible', f'{type(exc).__name__}: {exc}')

    def _show_pro_c3_validation_report(self):
        from .pro_c3_parameter_validation import summarize
        import json
        base = self.root / 'settings' / 'pro_c3_parameter_validation'
        reports = sorted(base.glob('*/report.json'), reverse=True) if base.is_dir() else []
        if not reports:
            QMessageBox.information(self, 'Validation Pro-C 3', 'Aucun rapport trouvé. Lance la validation d’abord.')
            return
        try:
            report = json.loads(reports[0].read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Validation Pro-C 3', str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Pro-C 3 — validation des paramètres')
        dialog.resize(720, 540)
        layout = QVBoxLayout(dialog)
        content = QTextEdit(dialog)
        content.setReadOnly(True)
        content.setPlainText(summarize(report) + '\n\n--- JSON complet ---\n' + json.dumps(report, ensure_ascii=False, indent=2))
        layout.addWidget(content)
        copy_btn = QPushButton('Copier le rapport')
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(content.toPlainText()))
        layout.addWidget(copy_btn)
        dialog.exec()

    def _show_pro_c3_bench_report(self):
        from .pro_c3_testbench import summarize
        import json
        base = self.root / 'settings' / 'pro_c3_testbench'
        reports = sorted(base.glob('*/report.json'), reverse=True) if base.is_dir() else []
        if not reports:
            QMessageBox.information(self, 'Test Bench Pro-C 3', 'Aucun rapport disponible. Lance le Test Bench en premier.')
            return
        try:
            report = json.loads(reports[0].read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Test Bench Pro-C 3', str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Pro-C 3 — dernier test sur signal synthétique')
        dialog.resize(720, 530)
        layout = QVBoxLayout(dialog)
        content = QTextEdit(dialog)
        content.setReadOnly(True)
        content.setPlainText(summarize(report) + '\n\n--- JSON complet ---\n' + json.dumps(report, ensure_ascii=False, indent=2))
        layout.addWidget(content)
        copy_btn = QPushButton('Copier le rapport')
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(content.toPlainText()))
        layout.addWidget(copy_btn)
        close_btn = QPushButton('Fermer')
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

    def _show_pro_c3_probe_report(self):
        from .pro_c3_multipoint import summarize
        import json
        try:
            report = json.loads((self.root / 'settings/pro_c3_multipoint.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            QMessageBox.information(self, 'Calibration multipoint', f'Grille introuvable : {exc}')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Pro-C 3 — points de calibration (lecture seule)')
        dialog.resize(710, 520)
        layout = QVBoxLayout(dialog)
        content = QTextEdit(dialog)
        content.setReadOnly(True)
        content.setPlainText(summarize(report) + '\n\n--- JSON complet ---\n' + json.dumps(report, ensure_ascii=False, indent=2))
        layout.addWidget(content)
        copy_btn = QPushButton('Copier les points')
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(content.toPlainText()))
        layout.addWidget(copy_btn)
        close_btn = QPushButton('Fermer')
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

    def _show_pro_c3_report(self):
        from .pro_c3_calibration import read_calibration_report, calibration_summary
        import json
        try:
            report = read_calibration_report(self.root)
        except (OSError, ValueError) as exc:
            QMessageBox.information(self, 'Calibration Pro-C 3', str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Pro-C 3 — Calibration Lab / lecture seule')
        dialog.resize(740, 520)
        layout = QVBoxLayout(dialog)
        notice = QLabel('Indices + valeurs affichées par Pro-C 3. Un seul point ne suffit pas à calibrer la conversion : aucun rendu automatique autorisé.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        content = QTextEdit(dialog)
        content.setReadOnly(True)
        content.setPlainText(calibration_summary(report) + '\n\n--- JSON complet ---\n' + json.dumps(report, ensure_ascii=False, indent=2))
        layout.addWidget(content)
        buttons = QHBoxLayout()
        copy_btn = QPushButton('Copier le rapport')
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(content.toPlainText()))
        buttons.addWidget(copy_btn)
        close_btn = QPushButton('Fermer')
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        dialog.exec()

    def _start_fx_worker(self, worker):
        self._fx_worker = worker
        worker.completed.connect(self._fx_work_completed)
        worker.failed.connect(self._fx_work_failed)
        worker.finished.connect(lambda w=worker: self._fx_work_finished(w))
        worker.start()

    def _fx_work_finished(self, worker):
        if self._fx_worker is worker:
            self._fx_worker = None
        worker.deleteLater()
        if self._player:
            self.fx_propose.setEnabled(True)
        self.fx_pro_c3.setEnabled(True)
        self.fx_pro_c3_probe.setEnabled(True)
        self.fx_pro_c3_bench.setEnabled(True)
        self.fx_pro_c3_validate.setEnabled(True)

    def _fx_work_failed(self, mode, message):
        self._set_fx_status(f'AI FX non appliqué : {message}')
        self._fx_plan = None

    def _fx_work_completed(self, mode, result, source):
        # Do not display stale advice if another song/mix was imported meanwhile.
        if mode == 'probe_compressor':
            from .pro_c3_multipoint import summarize
            self._set_fx_status('✓ Grille multipoint sauvegardée — compression toujours verrouillée.')
            return
        if mode == 'validate_compressor_parameters':
            from .pro_c3_parameter_validation import summarize
            self._set_fx_status('✓ Validation Pro-C 3 : ' + result.get('status', 'inconnu') +
                                ' — Auto Produce reste verrouillé pour la compression.')
            QMessageBox.information(self, 'Validation Pro-C 3', summarize(result) +
                                    '\n\nVoir / copier le rapport dans Tools.')
            return
        if mode == 'bench_compressor':
            from .pro_c3_testbench import summarize
            self._set_fx_status('✓ Test Bench terminé — ' + result.get('status', '') +
                                ' — compression automatique toujours verrouillée.')
            QMessageBox.information(self, 'Test Bench Pro-C 3', summarize(result) +
                                    '\n\nVoir / copier le dernier test dans Tools pour le rapport complet.')
            return
        if mode == 'diagnose_compressor':
            roles = result.get('required_status', {})
            detail = ', '.join(f'{name}: {status}' for name, status in roles.items())
            self._set_fx_status(
                f"✓ {result['plugin']} : {result['parameter_count']} paramètres inspectés. "
                f"Mapping proposé (non vérifié) — {detail}. "
                f"Rapport : {result['report_path']}. Affichages VST sauvegardés; aucune compression appliquée.")
            return
        current = str(Path(self._player.paths[self._selected]).resolve()) if self._player else ''
        if current != source or source != self._fx_source:
            self._set_fx_status('Ancienne analyse EQ ignorée : la source a changé.')
            return
        if mode == 'propose':
            self._fx_plan = result
            memory = result.get('eq_preference_context') or {}
            n = memory.get('total_confirmed', 0)
            self.fx_memory_status.setText(
                f'🧠 Mémoire EQ : {n} comparaison(s) A/B confirmée(s) prise(s) en compte.'
                if n else '🧠 Mémoire EQ : aucun choix Avant/Après confirmé pour le moment.')
            moves = result.get('moves', [])
            if not moves:
                self._set_fx_status('Aucune correction recommandée. ' + result.get('summary', '') + ' (Ce n’est pas une preuve que le mix est parfait.)')
                self.fx_creative.show()
                return
            details = '\n'.join(f"• {m['frequency_hz']:g} Hz : {m['gain_db']:+.2f} dB — {m['reason']}" for m in moves)
            answer = QMessageBox.question(self, 'AI FX — approuver un essai Pro-Q 4',
                f"{result['summary']}\n\n{details}\n\n"
                'Ces mesures ne prouvent aucun défaut audible.\n'
                'Créer un WAV séparé avec FabFilter Pro-Q 4 ?\n'
                'Ton prémix et ton master ne seront pas modifiés.',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                self._set_fx_status('Rendu Pro-Q 4 en cours… (fichier séparé)')
                self.fx_propose.setEnabled(False)
                self._start_fx_worker(AIFXWorker('render', source, self.root,
                                                plan=result, parent=self))
            else:
                self._set_fx_status('Proposition EQ refusée : aucun traitement effectué.')
        else:
            self._fx_audition = result.get('after')
            self._fx_render_report = result
            self._set_fx_status('✓ Essai EQ créé. Compare Avant / Après et confirme ta préférence si tu le souhaites. Le master reste inchangé.')
            self.fx_creative.hide()
            self.fx_listen.hide()
            try:
                self._fx_ab_player.load(source, self._fx_audition)
                self.fx_feedback_row.show()
            except Exception as exc:
                self._set_fx_status('Essai créé, mais lecture A/B indisponible : ' + str(exc))
                self.fx_listen.show()

    def _fx_stop_main_audio(self):
        if self._player:
            self._player.stop()
        if self._master_preview is not None:
            self._master_preview.pause()

    def _record_fx_preference(self, choice):
        if not self._fx_render_report or not self._fx_ab_player.sources:
            return
        try:
            from .eq_feedback import record_eq_choice
            report = self._fx_render_report
            count = record_eq_choice(self.root / 'settings' / 'eq_preferences.json',
                                     before=report['original'], after=report['after'],
                                     choice=choice, moves=report.get('moves', []),
                                     song=self.song_title_import.text().strip())
            label = 'Avant' if choice == 'before' else 'Après'
            self.fx_feedback_status.setText(f'✓ Préférence EQ enregistrée : {label} ({count} avis). Le prochain essai Hermes en tiendra compte. Le master reste inchangé.')
            self.fx_memory_status.setText(f'🧠 Mémoire EQ : {count} choix confirmé(s) dans l’historique.')
            self.fx_prefer_before.setEnabled(False)
            self.fx_prefer_after.setEnabled(False)
        except Exception as exc:
            self.fx_feedback_status.setText('Erreur d’enregistrement EQ : ' + str(exc))

    def _open_ai_fx_audition(self):
        if not self._fx_audition or not Path(self._fx_audition).is_file():
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._fx_audition)))

    def _save_preference(self):
        """Only explicit confirmation writes preference history, never AI auto-selection."""
        metrics = (self._ai_decision or {}).get('metrics')
        if not metrics or not self._report:
            self.pref_status.setText('Mesures DSP indisponibles : choix non enregistré.')
            return
        try:
            from .preference_learning import preference_path, save_choice
            song = self.song_title_import.text().strip()
            total = save_choice(preference_path(self.root), selected=self._selected,
                                metrics=metrics, ai_suggested=self._ai_decision.get('selected'),
                                song=song)
            self.pref_status.setText(f'✓ Préférence enregistrée ({total} choix). Elle guidera les prochaines évaluations.')
            self.pref_save.setEnabled(False)  # avoid accidental duplicate on current evaluation
        except Exception as exc:
            self.pref_status.setText(f'Impossible de sauvegarder : {exc}')

    def _clear_preferences_clicked(self):
        if QMessageBox.question(self, 'Effacer mes préférences',
            'Effacer tous les choix confirmés ? Les fichiers audio et références seront conservés.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            from .preference_learning import preference_path, clear_preferences
            clear_preferences(preference_path(self.root))
            self.pref_status.setText('Historique effacé. Les prochaines évaluations repartiront sans préférences.')
        except Exception as exc:
            self.pref_status.setText(f'Impossible d’effacer : {exc}')

    def _select(self, key):
        if getattr(self, '_selected', None) != key and hasattr(self, 'fx_status'):
            self._reset_ai_fx()
        self._selected = key
        if hasattr(self, 'unified') and key in self.cards:
            self.unified.set_waveform(self.cards[key].waveform._data)
        for k, card in self.cards.items():
            card.selected_style(k == key)
            card.waveform.setActive(k == key)
        self.continue_btn.setText(tr(self._language, 'continue', mix=VARIANT_LABELS[key]))
        self.ai_use.setVisible(bool(self._ai_decision and self._ai_decision.get('mode') == 'hermes' and self._ai_decision.get('selected') != key))
        if self._player and (not hasattr(self, 'unified') or not self.unified._files):
            self._player.switch(key)
        if hasattr(self, 'unified'):
            self.unified.select_mix(key)
        self.compression_preview.setEnabled(self._selected_mix_path() is not None)

    def _toggle_play(self):
        if hasattr(self, 'unified') and self.unified._files:
            self.unified.toggle()
            return
        if self._player:
            if self._fx_ab_player is not None:
                self._fx_ab_player.stop()
            self._player.toggle_play()

    def _stop(self):
        if hasattr(self, 'unified'):
            self.unified.stop()
        if self._player:
            self._player.stop()

    def _seek(self):
        if hasattr(self, 'unified') and self.unified._files:
            self.unified.seek.setValue(round(self.unified._max_ms * self.seek.value() / 10000))
            self.unified._seek()
            return
        if self._player:
            self._player._seek.setValue(self.seek.value())
            self._player.seek()

    def _set_level(self, enabled):
        if hasattr(self, 'unified') and self.unified._files:
            self.unified.match.setChecked(bool(enabled))
            return
        if self._player:
            self._player._match_check.setChecked(bool(enabled))

    def _sync_player(self):
        player = self._player
        if not player:
            return
        if hasattr(self, 'unified') and self.unified._files:
            return
        try:
            self.clock.setText(player._fmt(player._pos, player.rate) + ' / ' + player._fmt(player.frames, player.rate))
            if not self.seek.isSliderDown():
                self.seek.setValue(round(10000 * player._pos / player.frames))
            fraction = player._pos / max(1, player.frames)
            for card in self.cards.values():
                card.waveform.setPosition(fraction)
            self.play.setText('❚❚  Pause' if player._playing else '▶  Écouter')
            if not self._analysed and self._current_source == str(Path(player._comparison_source).resolve()):
                self.analysis_line.setText(player._analysis_status.text())
            if self._current_source != str(Path(player._comparison_source).resolve()):
                # Gen 2 was produced inside the shared player: update visible results.
                if not self.unified.is_busy():
                    self.unified.set_sources(player.paths, session_tag=str(Path(player._comparison_source).resolve()))
                    self.legacy_transport.hide()
                    self.level.hide()
                self._current_source = str(Path(player._comparison_source).resolve())
                self._report = Path(self._current_source)
                self._clear_ai_decision()
                self._reset_ai_fx()
                self._load_waveforms(player.paths)
                self._select('balanced')
                self._start_ai_evaluation(player.paths)
                self.level.setChecked(False)
                self.level.setEnabled(False)
                self._analysed = False
                for card in self.cards.values():
                    card.lufs.setText('— LUFS')
                self.gen2.setVisible(not self._report_is_gen2())
                self.analysis_line.setText('Nouvelle génération chargée — analyse en cours…')
        except (ValueError, ZeroDivisionError, OSError, TypeError):
            pass

    def _waveform_seek(self, key, fraction):
        """Choose the clicked mix and seek all synchronized audio to that location."""
        self._user_select(key)
        if self._player and self._player.frames:
            self.seek.setValue(round(10000 * fraction))
            self._seek()

    def _invalidate_waveforms(self):
        self._waveform_token = None
        for job in self._waveform_jobs:
            if job.isRunning():
                job.requestInterruption()
        for card in self.cards.values():
            card.waveform.setData(None)

    def _load_waveforms(self, paths):
        """Decode waveforms without blocking the UI; ignore late results from older songs."""
        self._invalidate_waveforms()
        self._waveform_token = str(id(paths)) + ':' + str(self._report)
        job = WaveformLoader(self._waveform_token, paths, self)
        self._waveform_jobs.append(job)
        self._waveform_loader = job
        job.generated.connect(self._waveform_ready)
        job.failed.connect(self._waveform_failed)
        job.finished.connect(lambda j=job: self._waveform_finished(j))
        job.start()

    def _waveform_ready(self, token, key, envelope):
        if token == self._waveform_token and key in self.cards:
            self.cards[key].waveform.setData(envelope)
            if key == self._selected and hasattr(self, 'unified'):
                self.unified.set_waveform(envelope)

    def _waveform_failed(self, token, key, message):
        if token == self._waveform_token and key in self.cards:
            self.cards[key].waveform.setToolTip('Forme d’onde indisponible : ' + message)

    def _waveform_finished(self, job):
        if job in self._waveform_jobs:
            self._waveform_jobs.remove(job)
        job.deleteLater()

    def _generate_next(self):
        if self._player is not None:
            self._player._start_gen2()

    def _show_details(self):
        # This is deliberately optional: the main flow doesn't require visiting the
        # complex inspector panel to pick a mix and continue.
        if self._player:
            self._player.show()
            self._player.raise_()
            self._player.activateWindow()

    def _on_unified_prepared(self, success):
        if not success:
            return
        if self._player:
            self._player.stop()
        if self._fx_ab_player is not None:
            self._fx_ab_player.stop()
        self.legacy_transport.hide()
        self.level.hide()
        self.unified.select_mix(self._selected)
        self.unified.approval_status.setText(
            'Original par défaut. Clique ♥ sur le mix et la compression voulus pour approuver la source du mastering.')

    def _selected_mix_path(self):
        """Prefer the source retained by the active common player, not legacy UI."""
        if hasattr(self, 'unified'):
            source = self.unified._sources.get(self._selected)
            if source and Path(source).is_file():
                return Path(source).resolve()
        if self._player is not None:
            source = self._player.paths.get(self._selected)
            if source and Path(source).is_file():
                return Path(source).resolve()
        return None

    def _sync_title_from_import(self, title):
        if self.song_title_master.text() != title:
            self.song_title_master.blockSignals(True)
            self.song_title_master.setText(title)
            self.song_title_master.blockSignals(False)
        self._master_song_title = title.strip() or None
        self._update_master_button()

    def _sync_title_from_master(self, title):
        if self.song_title_import.text() != title:
            self.song_title_import.blockSignals(True)
            self.song_title_import.setText(title)
            self.song_title_import.blockSignals(False)
        self._master_song_title = title.strip() or None
        self._update_master_button()

    def _song_title_for_export(self):
        """Infer song title from imported stems, not temporary Balanced WAV."""
        typed = self.song_title_master.text().strip()
        return typed or self._inferred_title_from_stems()

    def _inferred_title_from_stems(self):
        from .album_export_naming import song_name
        try:
            current = self.stems.states()
            if current:
                folder = Path(str(current[0]['file'])).resolve().parent
                return song_name(folder)
        except (ValueError, TypeError, KeyError, OSError, IndexError):
            pass
        return None

    def _master_key(self):
        """Session fingerprint: source, contents, chosen mix and export title."""
        source = self._master_input
        if source is None or not source.is_file():
            return None
        try:
            stat = source.stat()
            return (str(source.resolve()), stat.st_size, stat.st_mtime_ns,
                    self._master_mix_variant, self._song_title_for_export())
        except OSError:
            return None

    def _master_is_processed(self):
        if self._master_result is None or self._master_completed_key != self._master_key():
            return False
        output = self._master_result.get('file')
        return bool(output and Path(output).is_file())

    def _update_master_button(self):
        """Navigation and title editing never start FFmpeg; they only update state."""
        if not hasattr(self, 'master_run'):
            return
        running = self._master_worker is not None and self._master_worker.isRunning()
        processed = self._master_is_processed()
        self.master_run.setEnabled(not running and not processed and self._master_key() is not None)
        self.master_run.setText(tr(self._language,
                                   'master_done' if processed else 'master_action'))
        if processed:
            self.master_status.setText('✓  Master déjà créé. Aucun nouveau traitement nécessaire.')

    def _continue_mastering(self):
        """Surface any navigation exception instead of silent no-op."""
        try:
            self._prepare_mastering_navigation()
        except Exception as exc:
            QMessageBox.critical(
                self, 'Mastering',
                tr(self._language,'master_error',error=f'{type(exc).__name__}: {exc}'))

    def _prepare_mastering_navigation(self):
        """Choose approved audio and enter stage 3 without rendering."""
        source = self._selected_mix_path()
        if source is None:
            QMessageBox.warning(self, 'Mastering', tr(self._language,'missing_source'))
            return
        # Compressed previews must be explicitly heart-approved. Otherwise
        # mastering always receives the actual uncompressed premix.
        if hasattr(self, 'unified'):
            if self.unified.is_busy():
                QMessageBox.information(self, 'Mastering', tr(self._language,'busy'))
                return
            choice = self.unified.master_source(self._selected)
            if choice is not None and Path(choice).is_file():
                source = Path(choice)
        self._stop()
        if self._master_worker is not None and self._master_worker.isRunning():
            return
        new_variant = (self.unified.master_variant(self._selected)
                       if hasattr(self, 'unified') else self._selected)
        if self._master_input != source or self._master_mix_variant != new_variant:
            self._master_result = None
            self._master_completed_key = None
            self.master_open.hide()
            self.master_preflight.hide()
            self.master_preflight_status.clear()
            self._reset_master_preview()
            self.master_report.setText('')
            self.master_progress.setValue(0)
        self._master_input = source
        self._master_mix_variant = new_variant
        self._master_song_title = self._song_title_for_export()
        self.master_description.setText(tr(self._language,'source',name=source.name,variant=new_variant))
        if not self._master_is_processed():
            self.master_status.setText(tr(self._language,'master_ready'))
        self._update_master_button()
        self._go(3)

    def _open_master_stage(self):
        if self._master_worker is not None and self._master_worker.isRunning():
            self._go(3)
            return
        if self._selected_mix_path() is not None:
            self._continue_mastering()
        else:
            self._update_master_button()
            self._go(3)

    def _start_master(self):
        if self._master_worker is not None and self._master_worker.isRunning():
            return
        if self._master_input is None or not self._master_input.is_file():
            QMessageBox.warning(self, 'Source manquante', 'Sélectionne un mixage WAV avant Auto Master.')
            return
        if self._master_is_processed():
            self._update_master_button()
            return
        self._master_song_title = self._song_title_for_export()
        outdir = self.root / 'sound' / 'output' / 'auto_master'
        self._master_running_key = self._master_key()
        self._master_result = None
        self._master_completed_key = None
        self.master_open.hide()
        self.master_preflight.hide()
        self.master_preflight_status.clear()
        self._reset_master_preview()
        self.master_report.setText('')
        self.master_run.setEnabled(False)
        self.master_cancel.show()
        self.master_cancel.setEnabled(True)
        self.master_progress.setValue(0)
        self.master_status.setText('Vérification de la source et du moteur audio…')
        worker = AutoMasterWorker(self._master_input, outdir, self,
            song_title=self._master_song_title, mix_variant=self._master_mix_variant)
        self._master_worker = worker
        worker.stage.connect(self._master_stage)
        worker.completed.connect(self._master_done)
        worker.failed.connect(self._master_failed)
        worker.start()

    def _master_stage(self, stage, percent):
        self.master_status.setText(stage)
        self.master_progress.setValue(percent)

    def _master_done(self, result):
        self._master_result = result
        self._master_completed_key = self._master_running_key
        self._master_running_key = None
        status = result.get('status')
        self.master_cancel.hide()
        self._update_master_button()
        self.master_open.show()
        self.master_preflight.show()
        self.master_preflight.setEnabled(True)
        self._prepare_master_preview(result.get('file'))
        self.master_progress.setValue(100)
        self.master_status.setText('✓  Contrôles QC réussis' if status == 'qc_pass'
                                   else '⚠  Master créé, contrôle QC à revoir')
        self.master_report.setText(
            f"LUFS intégrés : {result['output_lufs']:.2f} (cible {result['target_lufs']:.1f})\n"
            f"True peak : {result['output_true_peak_dbtp']:.2f} dBTP "
            f"(plafond {result['target_true_peak_dbtp']:.1f})\n"
            f"PCM 24-bit · {result['output']['sample_rate']} Hz · WAV stéréo\n"
            f"{result['file']}\n" +
            ('À vérifier : ' + '; '.join(result['qc_issues']) if result['qc_issues'] else
             'QC technique OK. Écoute critique et validation album encore nécessaires.'))

    def _run_release_preflight(self):
        if not self._master_is_processed():
            QMessageBox.warning(self, 'Prépublication', 'Crée un master valide avant de lancer le contrôle.')
            return
        if self._preflight_worker is not None and self._preflight_worker.isRunning():
            return
        output = self._master_result['file']
        self.master_preflight.setEnabled(False)
        self.master_preflight_status.setText('Analyse du WAV exporté en cours…')
        worker = ReleasePreflightWorker(output, self)
        self._preflight_worker = worker
        worker.completed.connect(self._release_preflight_done)
        worker.failed.connect(self._release_preflight_failed)
        worker.finished.connect(lambda w=worker: w.deleteLater())
        worker.start()

    def _release_preflight_done(self, report):
        from .release_preflight import format_preflight
        self.master_preflight.setEnabled(True)
        self.master_preflight_status.setText(format_preflight(report) +
            '\nRapport JSON : ' + report.get('report_path', '(non enregistré)'))

    def _release_preflight_failed(self, message):
        self.master_preflight.setEnabled(True)
        self.master_preflight_status.setText('Contrôle impossible : ' + message)

    def _master_failed(self, message):
        self.master_cancel.hide()
        self.master_cancel.setEnabled(True)
        self._master_running_key = None
        self._update_master_button()
        self.master_status.setText('Mastering arrêté')
        self.master_report.setText(str(message))
        QMessageBox.warning(self, 'Auto Master', str(message))

    def _cancel_master(self):
        if self._master_worker is not None and self._master_worker.isRunning():
            self._master_worker.cancel()
            self.master_status.setText('Annulation demandée…')
            self.master_cancel.setEnabled(False)

    @staticmethod
    def _format_master_clock(ms):
        total = max(0, int(ms) // 1000)
        return f'{total // 60:02d}:{total % 60:02d}'

    def _master_player(self):
        """Create one QMediaPlayer and subscribe to actual transport state."""
        if self._master_preview is None:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            self._master_preview = QMediaPlayer(self)
            self._master_audio_output = QAudioOutput(self)
            self._master_audio_output.setVolume(0.7)
            self._master_preview.setAudioOutput(self._master_audio_output)
            self._master_preview.playbackStateChanged.connect(self._master_playback_state_changed)
            self._master_preview.positionChanged.connect(self._master_position_changed)
            self._master_preview.durationChanged.connect(self._master_duration_changed)
            self._master_preview.errorOccurred.connect(self._master_playback_error)
        return self._master_preview

    def _master_playback_state_changed(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        playing = state == QMediaPlayer.PlayingState
        self.master_listen.setText('Ⅱ  Pause' if playing else '▶  Play')
        self.master_stop.setEnabled(state != QMediaPlayer.StoppedState)

    def _master_position_changed(self, position):
        player = self._master_preview
        if player is None:
            return
        duration = max(0, player.duration())
        if not self._master_seek_dragging:
            self.master_seek.setValue(round(1000 * position / duration) if duration else 0)
            self.master_waveform.setPosition(position / duration if duration else 0)
        self.master_clock.setText(
            self._format_master_clock(position) + ' / ' + self._format_master_clock(duration))

    def _master_duration_changed(self, duration):
        position = self._master_preview.position() if self._master_preview else 0
        self.master_clock.setText(
            self._format_master_clock(position) + ' / ' + self._format_master_clock(duration))
        self._master_position_changed(position)

    def _master_seek_pressed(self):
        self._master_seek_dragging = True

    def _master_seek_released(self):
        self._master_seek_dragging = False
        self._seek_master_fraction(self.master_seek.value() / 1000.0)

    def _master_seek_waveform(self, fraction):
        self._seek_master_fraction(fraction)

    def _seek_master_fraction(self, fraction):
        player = self._master_preview
        if player is None or not self._master_preview_path:
            return
        duration = player.duration()
        if duration <= 0:
            return
        fraction = max(0., min(1., float(fraction)))
        player.setPosition(round(duration * fraction))
        self.master_waveform.setPosition(fraction)

    def _master_playback_error(self, error, message):
        if error:
            self.master_listen.setText('▶  Play')
            self.master_listen.setToolTip('Erreur de lecture : ' + str(message))

    def _stop_master_preview(self):
        if self._master_preview is not None:
            self._master_preview.stop()
        self.master_seek.setValue(0)
        self.master_waveform.setPosition(0)
        self.master_listen.setText('▶  Play')
        self.master_clock.setText('00:00 / ' + (
            self._format_master_clock(self._master_preview.duration()) if self._master_preview else '00:00'))

    def _reset_master_preview(self):
        """Forget UI/preview when master changes; ignore stale waveform jobs."""
        if not hasattr(self, 'master_player_panel'):
            return
        self._master_waveform_token += 1
        for job in self._master_waveform_jobs:
            job.requestInterruption()
        self._master_preview_path = None
        if self._master_preview is not None:
            self._master_preview.stop()
            from PySide6.QtCore import QUrl
            self._master_preview.setSource(QUrl())
        self.master_waveform.setData(None)
        self.master_waveform.setPosition(0)
        self.master_seek.setValue(0)
        self.master_clock.setText('00:00 / 00:00')
        self.master_listen.setText('▶  Play')
        self.master_player_panel.hide()

    def _prepare_master_preview(self, filename):
        """Show player only for a real mastered WAV; decode waveform in background."""
        if not filename or not Path(filename).is_file():
            self._reset_master_preview()
            return
        self._reset_master_preview()
        path = str(Path(filename).resolve())
        self._master_preview_path = path
        self.master_player_panel.show()
        self.master_stop.setEnabled(False)
        self._master_player()
        from PySide6.QtCore import QUrl
        self._master_preview.setSource(QUrl.fromLocalFile(path))
        self._master_waveform_token += 1
        token = str(self._master_waveform_token)
        job = WaveformLoader(token, {'master': path}, self)
        self._master_waveform_loader = job
        self._master_waveform_jobs.append(job)
        job.generated.connect(self._master_waveform_ready)
        job.failed.connect(self._master_waveform_failed)
        job.finished.connect(lambda j=job: self._master_waveform_finished(j))
        job.start()

    def _master_waveform_ready(self, token, key, envelope):
        if key == 'master' and token == str(self._master_waveform_token):
            self.master_waveform.setData(envelope)

    def _master_waveform_failed(self, token, key, message):
        if key == 'master' and token == str(self._master_waveform_token):
            self.master_waveform.setToolTip('Aperçu indisponible : ' + str(message))

    def _master_waveform_finished(self, job):
        if job in self._master_waveform_jobs:
            self._master_waveform_jobs.remove(job)

    def _listen_master(self):
        """Play / pause real QMediaPlayer; never render another master on click."""
        if not self._master_preview_path or not Path(self._master_preview_path).is_file():
            QMessageBox.warning(self, 'Master introuvable', 'Le fichier master n’est plus disponible.')
            return
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            player = self._master_player()
            if player.playbackState() == QMediaPlayer.PlayingState:
                player.pause()
            else:
                player.play()
        except Exception as exc:
            QMessageBox.warning(self, 'Lecture indisponible',
                'Impossible de lire ce WAV avec la sortie audio Qt : ' + str(exc))

    def _open_master_file(self):
        if not self._master_result:
            return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        output = Path(self._master_result['file'])
        if output.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(output.parent)))

    def _handoff_to_advanced_master(self):
        source = self._master_input
        if source is None or not source.is_file():
            QMessageBox.information(self, 'Aucun mix', 'Choisis d’abord une version de ton mix.')
            return
        folder = self.root / 'sound' / 'source'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ('AutoStudio-' + source.name)
        if not target.exists():
            shutil.copy2(source, target)
        self.openMastering.emit(str(target))

    def _close_player(self):
        if hasattr(self, 'unified') and not self.unified.is_busy():
            self.unified.shutdown()
        if hasattr(self, 'compression_preview'):
            self.compression_preview.setEnabled(False)
        if self._player:
            if self._player_busy():
                # Never delete a Qt object owning active QThreads.
                return
            player, self._player = self._player, None
            player.stop()
            player.close()
            player.deleteLater()

    def shutdown(self):
        if hasattr(self, 'unified'):
            if self.unified.is_busy():
                self.unified.worker.wait(900000)  # no QThread destroyed while rendering
            self.unified.shutdown()
        if self._fx_ab_player is not None:
            self._fx_ab_player.shutdown()
        if self._album_page is not None:
            self._album_page.shutdown()
        self._reset_master_preview()
        for job in self._master_waveform_jobs:
            job.requestInterruption()
        for job in self._master_waveform_jobs:
            job.wait(5000)
        if self._master_worker is not None and self._master_worker.isRunning():
            self._master_worker.cancel()
            self._master_worker.wait(5000)
        self._invalidate_waveforms()
        for job in self._ai_jobs:
            job.wait(45000)
        # Wait only during application shutdown to avoid deleting a running QThread.
        for job in self._waveform_jobs:
            job.wait(3000)
        self._close_player()
