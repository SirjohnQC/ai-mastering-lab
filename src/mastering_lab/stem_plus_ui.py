"""STEM+ dedicated mixer page, independent from stereo mastering."""
from __future__ import annotations
from pathlib import Path
import json,sys
from PySide6.QtCore import Qt,QProcess,QTimer,Signal,QObject,QThread,Slot,QSettings,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,
 QFileDialog,QScrollArea,QGridLayout,QDoubleSpinBox,QSlider,QCheckBox,QMessageBox,QPlainTextEdit,QFrame,QProgressBar,QGroupBox,QListWidget,QComboBox,QDialog,QDialogButtonBox,QInputDialog,QProgressDialog)
from .stem_plus_audio import LiveStemMixer
from .stem_mixer import config_template, classify_stem
from .plugin_registry import selected_proq4, read_settings, ROLES

class _OllamaReviewWorker(QObject):
    """Runs the potentially slow Ollama request outside the Qt GUI thread."""
    finished = Signal(object, object)
    def __init__(self, proposals, model):
        super().__init__()
        self.proposals = proposals
        self.model = model

    @Slot()
    def run(self):
        try:
            from .ai_review import review_proposals, merge_review
            reviews = review_proposals(self.proposals, model=self.model, timeout=60)
            self.finished.emit(merge_review(self.proposals, reviews), None)
        except Exception as exc:
            self.finished.emit(self.proposals, str(exc))


class StemPlusPage(QWidget):
    sourceExported = Signal(str)
    audioLoaded = Signal(int, str)
    productionStatus = Signal(str)
    productionFinished = Signal(str)
    def __init__(self,root:Path,folder:Path|None=None):
        super().__init__();self.root=root;self.engine=LiveStemMixer();self.rows=[];self.config=None;self._busy=False;self._selected_files_mode=False;self._selected_config_path=root/'sound'/'stem_projects'/'manual-selection'/'stem-mix.json'
        self.session=QSettings('Losing Motivation', 'AI Mastering Lab')
        # The advanced console must not force every workspace above laptop height.
        page_layout=QVBoxLayout(self)
        page_layout.setContentsMargins(0,0,0,0)
        scroll=QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content=QWidget()
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        outer=QVBoxLayout(content)
        title=QLabel('STEM+  |  MULTITRACK STUDIO');title.setStyleSheet('font-size:22px;font-weight:bold;color:#b2a9ff');outer.addWidget(title)
        description=QLabel('Console de prémix : Solo / Mute / Gain / Pan en live. EQ Pro-Q 4 disponible après préparation hors ligne. Aucun master final ici.')
        description.setWordWrap(True);outer.addWidget(description)
        choose=QHBoxLayout();self.folder=QLineEdit(str(folder or root/'sound'/'stems'));choose.addWidget(self.folder,1)
        browse=QPushButton('Dossier stems');browse.clicked.connect(self.browse);choose.addWidget(browse)
        pick=QPushButton('Choisir fichiers…');pick.clicked.connect(self.choose_files);choose.addWidget(pick)
        self.folder.returnPressed.connect(self.load_folder)
        outer.addLayout(choose)
        quick=QGroupBox('AUTO STUDIO — Mode simple')
        quick_lay=QVBoxLayout(quick)
        quick_info=QLabel('1. Charge les stems d’une chanson   →   2. Auto Produce   →   3. Écoute les trois mixages et leur analyse.\nUne seule approbation des FX avant le rendu; les fichiers originaux ne sont jamais écrasés.')
        quick_info.setWordWrap(True);quick_lay.addWidget(quick_info)
        quick_bar=QHBoxLayout()
        self.auto_produce_btn=QPushButton('✨ AUTO PRODUCE — FX → MIX → ANALYSE')
        self.auto_produce_btn.setObjectName('primary')
        self.auto_produce_btn.clicked.connect(self.start_guided_production)
        quick_bar.addWidget(self.auto_produce_btn,1)
        self.quick_compare=QPushButton('🎧 Derniers mixages')
        self.quick_compare.clicked.connect(self.open_auto_mix_comparison)
        quick_bar.addWidget(self.quick_compare)
        self.advanced_toggle=QCheckBox('Advanced')
        self.advanced_toggle.toggled.connect(self._set_advanced_mode)
        quick_bar.addWidget(self.advanced_toggle)
        quick_lay.addLayout(quick_bar)
        self.pipeline_step=QLabel('Prêt — charge tes stems pour commencer.')
        self.pipeline_step.setWordWrap(True)
        quick_lay.addWidget(self.pipeline_step)
        outer.addWidget(quick)
        self.selection_info=QLabel('Mode dossier : tous les stems compatibles du dossier. Mode fichiers : seulement ceux choisis.')
        self.selection_info.setWordWrap(True);outer.addWidget(self.selection_info)
        bar=QHBoxLayout()
        self.play=QPushButton('▶ Play');self.play.clicked.connect(self.toggle_play);bar.addWidget(self.play)
        self.stop_btn=QPushButton('■ Stop');self.stop_btn.clicked.connect(self.stop);bar.addWidget(self.stop_btn)
        self.all_btn=QPushButton('All tracks');self.all_btn.clicked.connect(self.all_tracks);bar.addWidget(self.all_btn)
        self.seek=QSlider(Qt.Horizontal);self.seek.setRange(0,1000);self.seek.sliderReleased.connect(self.seek_to);bar.addWidget(self.seek,1)
        self.time=QLabel('00:00 / 00:00');bar.addWidget(self.time);outer.addLayout(bar)
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        self.track_holder=QWidget();self.track_layout=QHBoxLayout(self.track_holder);self.track_layout.setAlignment(Qt.AlignLeft)
        self.track_layout.addStretch();scroll.setWidget(self.track_holder);outer.addWidget(scroll,1)
        rack=QGroupBox('FX RACK — piste sélectionnée')
        rack_layout=QVBoxLayout(rack)
        self.rack_label=QLabel('Clique une piste pour inspecter les effets.');self.rack_label.setWordWrap(True);rack_layout.addWidget(self.rack_label)
        self.rack_eq=QCheckBox('FX chain ON (prepared audio)');self.rack_eq.toggled.connect(self.rack_toggle_eq);rack_layout.addWidget(self.rack_eq)
        self.rack_other=QLabel('FX chains rendered offline through your installed VST3s. Select plugin roles, reorder and prepare.\nPlugin defaults or compatible JUCE .state snapshots. Individual FX can be inspected; real-time plugin editors are not yet available.')
        self.rack_other.setStyleSheet('color:#a6abc1');rack_layout.addWidget(self.rack_other)
        self.fx_list=QListWidget();self.fx_list.setMaximumHeight(120);rack_layout.addWidget(self.fx_list)
        fx_buttons=QHBoxLayout()
        self.track_fx_buttons=[]
        self.fx_role=QComboBox()
        for key,label in ROLES.items():
            if key != 'limiter':self.fx_role.addItem(label,key)
        fx_buttons.addWidget(self.fx_role)
        for name, fn in [('Add FX',self.fx_add),('Remove',self.fx_remove),('↑',self.fx_up),('↓',self.fx_down),('Bypass FX',self.fx_bypass),('Load state',self.fx_load_state),('Clear state',self.fx_clear_state),('Inspect FX',self.fx_inspect),('Edit parameters',self.fx_edit_parameters)]:
            btn=QPushButton(name);btn.clicked.connect(fn);fx_buttons.addWidget(btn);self.track_fx_buttons.append(btn)
        rack_layout.addLayout(fx_buttons)
        self.ai_review_check=QCheckBox('AI review via local Ollama (optional, measurements only)')
        self.ai_review_check.setChecked(True)
        rack_layout.addWidget(self.ai_review_check)
        self.ai_model_btn=QPushButton('⚙ Ollama settings / test models')
        self.ai_model_btn.clicked.connect(self.configure_ai_model);rack_layout.addWidget(self.ai_model_btn)
        self.fx_suggest_btn=QPushButton('✨ Suggest FX chains for all stems')
        self.fx_suggest_btn.clicked.connect(self.fx_suggest_all);rack_layout.addWidget(self.fx_suggest_btn)
        self.fx_prepare_btn=QPushButton('Prepare selected FX chains (offline)')
        self.fx_prepare_btn.clicked.connect(self.prepare_fx);rack_layout.addWidget(self.fx_prepare_btn)
        self.advanced_rack=rack;outer.addWidget(rack)
        master=QHBoxLayout();master.addWidget(QLabel('Master monitoring'))
        self.master_fader=QSlider(Qt.Horizontal);self.master_fader.setRange(-300,60);self.master_fader.setValue(0)
        self.master_fader.valueChanged.connect(self.master_changed);master.addWidget(self.master_fader,1)
        self.master_readout=QLabel('0.0 dB (en plus des −12 dB de sécurité)');master.addWidget(self.master_readout)
        self.advanced_master=QWidget();self.advanced_master.setLayout(master);outer.addWidget(self.advanced_master)
        buttons=QHBoxLayout()
        self.save_btn=QPushButton('Save stem-mix.json');self.save_btn.clicked.connect(self.save_config);buttons.addWidget(self.save_btn)
        self.prep=QPushButton('Prepare Pro-Q 4 EQ (offline)');self.prep.clicked.connect(self.prepare_eq);buttons.addWidget(self.prep)
        self.render=QPushButton('Render full mix');self.render.clicked.connect(self.render_mix);buttons.addWidget(self.render)
        self.auto_mix_btn=QPushButton('✨ Auto Mix: 3 variants');self.auto_mix_btn.clicked.connect(self.auto_mix_candidates);buttons.addWidget(self.auto_mix_btn)
        self.compare_btn=QPushButton('🎧 Compare Auto Mix');self.compare_btn.clicked.connect(self.open_auto_mix_comparison);buttons.addWidget(self.compare_btn)
        self.to_master=QPushButton('→ Send premix to MASTERING');self.to_master.clicked.connect(self.export_to_mastering);buttons.addWidget(self.to_master)
        self.advanced_actions=QWidget();self.advanced_actions.setLayout(buttons);outer.addWidget(self.advanced_actions)
        self.status=QLabel('Choisis un dossier ou des fichiers stems pour commencer. Le dossier se charge automatiquement.');self.status.setWordWrap(True);outer.addWidget(self.status)
        self.busy_bar=QProgressBar();self.busy_bar.setRange(0,0);self.busy_bar.setVisible(False);outer.addWidget(self.busy_bar)
        self.busy_label=QLabel('');self.busy_label.setVisible(False);outer.addWidget(self.busy_label)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(90);outer.addWidget(self.log)
        self.job=QProcess(self);self.job.setWorkingDirectory(str(root));self.job.setProcessChannelMode(QProcess.MergedChannels)
        self.job.finished.connect(self.job_done)
        self.job.finished.connect(lambda *_:self._set_busy(False))
        self.job.errorOccurred.connect(lambda *_:self._set_busy(False))
        self.selected_track=None;self.last_export=None;self._ai_thread=None;self._ai_worker=None;self._latest_comparison=None;self._guided_pipeline=False;self._guided_cancelled=False;self._guided_progress=None;self._compare_window=None
        self.timer=QTimer(self);self.timer.setInterval(80);self.timer.timeout.connect(self.refresh_transport);self.timer.start()
        self._set_advanced_mode(False)
        self.refresh_action_availability()
        QTimer.singleShot(0, self._restore_previous_selection)

    def _set_advanced_mode(self, enabled):
        self.advanced_rack.setVisible(bool(enabled))
        self.advanced_master.setVisible(bool(enabled))
        self.advanced_actions.setVisible(bool(enabled))

    def _show_guided_progress(self, message):
        # Application-modal progress prevents edits/restarts during an Auto Studio job.
        # Approval is handled by a separate modal dialog between processing stages.
        if not self._guided_pipeline or self._guided_cancelled:
            return
        if self._guided_progress is None:
            progress=QProgressDialog(message, 'Annuler', 0, 0, self)
            progress.setWindowTitle('Auto Studio — Traitement en cours')
            progress.setWindowModality(Qt.ApplicationModal)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.setMinimumWidth(460)
            progress.canceled.connect(self._cancel_guided_production)
            self._guided_progress=progress
        self._guided_progress.setLabelText(message+'\n\nLes autres commandes sont verrouillées pendant le traitement.')
        self._guided_progress.show()

    def _hide_guided_progress(self):
        if self._guided_progress is not None:
            dialog=self._guided_progress
            self._guided_progress=None
            dialog.blockSignals(True)
            dialog.close()
            dialog.deleteLater()

    def _cancel_guided_production(self):
        if not self._guided_pipeline:
            return
        self._guided_cancelled=True
        self._guided_pipeline=False
        self._hide_guided_progress()
        if self.job.state()!=QProcess.NotRunning:
            self.job.kill()  # Only the subprocess; original WAVs are not touched.
        # QThread/Ollama cannot safely be terminated: ignore its eventual result.
        self._auto_step('Auto Produce annulé — arrêt des traitements. Le résultat Ollama en cours sera ignoré.')
        self._set_busy(False)
        self.refresh_action_availability()

    def _auto_step(self, message):
        if self._guided_pipeline and not self._guided_cancelled:
            self._show_guided_progress(message)
        self.pipeline_step.setText(message)
        self.status.setText(message)
        self.log.appendPlainText('AUTO STUDIO · ' + message)
        self.productionStatus.emit(message)

    def _stop_guided_production(self, reason):
        self._guided_pipeline=False
        self._hide_guided_progress()
        self._auto_step(reason)
        self.refresh_action_availability()

    def start_guided_production(self):
        """One approved FX stage, then chained offline FX / three renders / AI comparison."""
        if not self._require_stems('Auto Produce'):
            return
        if self._guided_pipeline or self.job.state()!=QProcess.NotRunning or self._ai_thread is not None:
            QMessageBox.information(self,'Traitement déjà en cours','Attends la fin du traitement actuel.')
            return
        self._guided_cancelled=False
        self._guided_pipeline=True
        self._auto_step('Étape 1/4 — Analyse des stems et suggestions de FX…')
        self.refresh_action_availability()
        try:
            QTimer.singleShot(0, lambda: self.fx_suggest_all() if self._guided_pipeline else None)
        except Exception as exc:
            self._stop_guided_production(f'Auto Produce arrêté : {exc}')
            QMessageBox.warning(self,'Auto Produce',str(exc))

    def _guided_render_mix(self):
        self._auto_step('Étape 3/4 — Rendu des trois variantes (Balanced / Vocal Focus / Punchy)…')
        if not self.save_config():
            return
        self._job(self.root/'scripts'/'auto_mix_candidates.py',
                  ['--folder',self.folder.text().strip(),'--config',str(self._config_path()),
                   '--prepared',str(self.cache_path()/'prepared.json'),
                   '--out',str(self.cache_path()/'auto_mix')],'auto_mix')
        if self.job.state()==QProcess.NotRunning:
            self._stop_guided_production('Auto Produce arrêté : moteur de rendu non démarré.')

    def _set_busy(self, active, label=''):
        self.busy_bar.setVisible(bool(active))
        self.busy_label.setVisible(bool(active))
        if active:self.busy_label.setText(label or 'Traitement en cours…')

    def _require_stems(self, action='cette action'):
        if self.rows and self.config is not None:
            return True
        QMessageBox.information(self, 'Aucun stem chargé',
            f'Impossible de lancer {action} : aucune piste audio n’est chargée.\n\n'
            'Clique sur « Choisir fichiers… » ou « Dossier stems » pour commencer.')
        self.status.setText('Aucun audio chargé — sélectionne des stems avant de lancer un traitement.')
        return False

    def refresh_action_availability(self):
        """Keep dependent actions disabled until audio exists; allow browsing and AI setup."""
        loaded=bool(self.rows) and self.config is not None
        running=self.job.state()!=QProcess.NotRunning or self._ai_thread is not None
        ready=loaded and not running and not self._guided_pipeline
        self.auto_produce_btn.setEnabled(loaded and not running and not self._guided_pipeline)
        self.quick_compare.setEnabled(loaded and not running and not self._guided_pipeline and self._find_comparison_report() is not None)
        for widget in (self.play,self.stop_btn,self.all_btn,self.seek,self.save_btn,
                       self.prep,self.render,self.auto_mix_btn,self.to_master,self.fx_prepare_btn,
                       self.fx_suggest_btn,self.fx_list,self.fx_role,self.rack_eq,
                       self.master_fader,*self.track_fx_buttons):
            widget.setEnabled(ready)
        if ready and self.selected_track is not None:
            self.rack_eq.setEnabled(self.selected_track in self.engine.wet)
        for row in self.rows:
            for key in ('gain','fader','solo','mute','pan','eq'):
                row[key].setEnabled(ready)
        self.compare_btn.setEnabled(not running and not self._guided_pipeline and self._find_comparison_report() is not None)
        if not loaded:
            self.rack_label.setText('Charge des stems pour accéder au FX Rack.')
            self.fx_list.clear()

    def _remember_selection(self, mode: str, folder: Path, files=None):
        """Remember only paths, not secrets or audio; user project settings remain in JSON."""
        self.session.setValue('stem_plus/last_mode', mode)
        self.session.setValue('stem_plus/last_folder', str(folder))
        self.session.setValue('stem_plus/last_files', json.dumps([str(p) for p in (files or [])]))
        self.session.sync()

    def _restore_previous_selection(self):
        """Restore previous project without overwriting its saved FX settings."""
        mode = self.session.value('stem_plus/last_mode', '', type=str)
        folder = Path(self.session.value('stem_plus/last_folder', '', type=str) or self.folder.text())
        if mode not in ('files', 'folder'):
            return
        self.folder.setText(str(folder))
        if mode == 'folder':
            if folder.is_dir():
                self.load_folder(quiet=True)
            else:
                self.status.setText('Dernier dossier STEM+ introuvable. Choisis-en un autre.')
            return
        try:
            remembered = json.loads(self.session.value('stem_plus/last_files', '[]', type=str))
            if not isinstance(remembered, list) or not remembered:
                return
            files = [Path(f) for f in remembered]
            missing = [str(p) for p in files if not p.is_file()]
            if missing:
                self.status.setText(f'Dernière sélection indisponible : {len(missing)} fichier(s) déplacé(s).')
                self.log.appendPlainText('Stems manquants :\n' + '\n'.join(missing[:8]))
                return
            from .stem_selection import selection_config
            old_config = self._selected_config_path
            config = json.loads(old_config.read_text(encoding='utf-8')) if old_config.is_file() else None
            expected = [str(p.resolve()) for p in files]
            actual = [str(Path(t['file']).resolve()) for t in config.get('tracks', [])] if isinstance(config,dict) else []
            if actual != expected:
                config = selection_config(files)
            self._selected_files_mode = True
            self.selection_info.setText(f'Mode fichiers restauré : {len(files)} pistes. FX et mix sauvegardés conservés.')
            self._load_config(config)
        except Exception as exc:
            self.log.appendPlainText(f'Restauration STEM+ impossible : {exc}')
            self.status.setText('Dernière session non restaurée — sélectionne tes stems.')

    def browse(self):
        folder=QFileDialog.getExistingDirectory(self,'Choose STEM+ folder',self.folder.text())
        if folder:
            self.folder.setText(folder)
            self.load_folder()

    def _config_path(self):
        if self._selected_files_mode:
            return self._selected_config_path
        return Path(self.folder.text().strip())/'stem-mix.json'

    def choose_files(self):
        """Select explicit stems, excluding unrelated MP3s in their directories."""
        start = self.folder.text().strip()
        if not Path(start).is_dir(): start = str(self.root / 'sound' / 'stems')
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Choisir les stems (Ctrl/Shift pour plusieurs)', start,
            'Stems WAV/FLAC/AIFF (*.wav *.flac *.aiff *.aif);;MP3 (*.mp3);;All audio (*.wav *.flac *.aiff *.aif *.mp3)')
        if not files: return
        try:
            from .stem_selection import selection_config
            config = selection_config([Path(f) for f in files])
            # A dedicated project avoids rewriting the original stem-mix.json.
            self._selected_files_mode=True
            self._selected_config_path.parent.mkdir(parents=True, exist_ok=True)
            self._selected_config_path.write_text(json.dumps(config,indent=2,ensure_ascii=False),encoding='utf-8')
            self.folder.setText(str(Path(files[0]).parent))
            self.selection_info.setText(f'Mode fichiers : {len(files)} pistes sélectionnées uniquement. Configuration indépendante.')
            self._load_config(config)
            self._remember_selection('files', Path(files[0]).parent, files)
        except Exception as e: QMessageBox.warning(self,'STEM+ selection failed',str(e))

    def remove_stem_from_selection(self, file_path):
        """Exclude one input from this session, preserving surviving mixer/FX settings.

        Switch folder projects to a dedicated manual selection so the source
        directory and its stem-mix.json remain untouched. No WAV is deleted.
        """
        if self._guided_pipeline or self._ai_thread is not None or self.job.state() != QProcess.NotRunning:
            raise RuntimeError('Un traitement est en cours; annule-le avant de modifier les stems.')
        requested = str(Path(file_path).resolve()).casefold()
        entries = [{k:v for k,v in item.items() if k != 'solo'} for item in self.states()]
        survivors = [entry for entry in entries if str(Path(entry['file']).resolve()).casefold() != requested]
        if len(survivors) == len(entries):
            raise ValueError('Ce fichier ne fait plus partie de la sélection.')
        # Stop playback before replacing its audio buffers.
        self.stop()
        if not survivors:
            self.clear_rows()
            self._selected_files_mode = True
            self.selection_info.setText('Aucun stem sélectionné.')
            self._remember_selection('files', Path(self.folder.text().strip()), [])
            self.audioLoaded.emit(0, '')
            self.status.setText('Tous les stems ont été retirés de la sélection.')
            return True
        candidate = {**self.config, 'tracks': survivors}
        # Load in memory before updating the saved selection. A failure doesn't
        # overwrite the existing project config or remove any source WAV.
        self._selected_files_mode = True
        self._load_config(candidate)
        output = self._selected_config_path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(candidate, indent=2, ensure_ascii=False), encoding='utf-8')
        self._remember_selection('files', Path(self.folder.text().strip()), [x['file'] for x in survivors])
        self.selection_info.setText(f'Mode fichiers personnalisés : {len(survivors)} pistes, réglages conservés.')
        return True

    def _load_config(self, config):
        self._latest_comparison = None
        paths=[Path(x['file']) for x in config['tracks']]
        if not paths:raise ValueError('No stems selected')
        self.engine.load(paths,[{**x,'solo':False} for x in config['tracks']])
        self.clear_rows()
        self.config=config
        for i,entry in enumerate(config['tracks']): self.make_row(i,entry)
        self.status.setText(f'{len(paths)} stems chargés · {self.engine.duration_ms/1000:.1f} sec · monitoring −12 dB')
        cache=self.cache_path()/'prepared.json'
        if cache.is_file():
            prepared=json.loads(cache.read_text(encoding='utf-8')).get('processed',{})
            for key,path in prepared.items():
                try:
                    from .fx_chain import chain_fingerprint
                    idx=int(key)
                    chain=config['tracks'][idx].get('fx_chain',[])
                    report=json.loads(cache.read_text(encoding='utf-8'))
                    if chain and report.get('fx_reports',{}).get(key,{}).get('fingerprint') != chain_fingerprint(Path(config['tracks'][idx]['file']),chain):
                        raise ValueError('FX cache is stale')
                    self.engine.set_processed(idx,Path(path))
                except Exception as e:self.log.appendPlainText(f'Cached EQ ignored: {e}')
        self.update_states()
        self.refresh_action_availability()
        self.audioLoaded.emit(len(self.rows), Path(self.folder.text()).name)


    def load_folder(self, quiet=False):
        folder=Path(self.folder.text().strip())
        try:
            if not folder.is_dir():raise ValueError(f'Folder not found: {folder}')
            self._selected_files_mode=False
            config=json.loads(self._config_path().read_text(encoding='utf-8')) if self._config_path().is_file() else config_template(folder)
            self.selection_info.setText('Mode dossier : toutes les pistes découvertes. Pour exclure un MP3, clique « Choisir fichiers… ».')
            self._load_config(config)
            self._remember_selection('folder',folder)
        except Exception as e:
            if quiet:
                self.status.setText(f'Impossible de restaurer le dossier précédent : {e}')
                self.log.appendPlainText(f'Restauration dossier : {e}')
            else:
                QMessageBox.warning(self,'STEM+ load failed',str(e))

    def clear_rows(self):
        for row in self.rows:row['frame'].setParent(None);row['frame'].deleteLater()
        self.rows=[];self.selected_track=None
        self.config=None
        self.refresh_action_availability()

    def make_row(self,i,entry):
        panel=QFrame();panel.setObjectName('stemRow')
        panel.setStyleSheet('QFrame#stemRow{border:1px solid #3c4560;border-radius:8px;padding:5px;background:#1c2434;}')
        panel.setMinimumWidth(135);panel.setMaximumWidth(160)
        layout=QVBoxLayout(panel)
        name=QPushButton(Path(entry['file']).stem.replace('_',' '));name.setToolTip(str(entry['file']))
        name.clicked.connect(lambda checked=False,index=i:self.select_track(index));layout.addWidget(name)
        meter=QProgressBar();meter.setRange(0,90);meter.setValue(0);meter.setTextVisible(False)
        meter.setFixedHeight(9);meter.setStyleSheet('QProgressBar{background:#252b38;border:0;border-radius:4px;}QProgressBar::chunk{background:#50bd9c;}')
        layout.addWidget(meter)
        frow=QHBoxLayout()
        fader=QSlider(Qt.Vertical);fader.setRange(-180,180);fader.setValue(round(float(entry.get('gain_db',0))*10))
        fader.setTickInterval(60);fader.setTickPosition(QSlider.TicksLeft);fader.setMinimumHeight(165)
        frow.addWidget(fader,1)
        vals=QVBoxLayout();vals.addWidget(QLabel('Gain'))
        gain=QDoubleSpinBox();gain.setRange(-18,18);gain.setSingleStep(.5);gain.setDecimals(1)
        gain.setSuffix(' dB');gain.setValue(float(entry.get('gain_db',0)));vals.addWidget(gain)
        vals.addStretch();frow.addLayout(vals);layout.addLayout(frow)
        solo=QCheckBox('Solo');mute=QCheckBox('Mute');mute.setChecked(bool(entry.get('mute',False)))
        buttons=QHBoxLayout();buttons.addWidget(solo);buttons.addWidget(mute);layout.addLayout(buttons)
        pan=QDoubleSpinBox();pan.setRange(-1,1);pan.setSingleStep(.1);pan.setDecimals(2)
        pan.setValue(float(entry.get('pan',0)));pan.setPrefix('Pan ');layout.addWidget(pan)
        eq=QCheckBox('FX ON');eq.setChecked(bool(entry.get('eq',False)));layout.addWidget(eq)
        row={'frame':panel,'solo':solo,'mute':mute,'gain':gain,'fader':fader,'meter':meter,'pan':pan,'eq':eq,'entry':entry}
        self.rows.append(row)
        fader.valueChanged.connect(lambda value,w=gain:w.setValue(value/10))
        gain.valueChanged.connect(lambda value,w=fader:w.setValue(round(value*10)))
        for widget,signal in ((solo,solo.toggled),(mute,mute.toggled),(gain,gain.valueChanged),(pan,pan.valueChanged),(eq,eq.toggled)):
            signal.connect(self.update_states)
        self.track_layout.insertWidget(self.track_layout.count()-1,panel)
        if self.selected_track is None:self.select_track(i)

    def select_track(self,index):
        self.selected_track=index
        if index>=len(self.rows):return
        name=Path(self.rows[index]['entry']['file']).name
        self.rack_label.setText(f'{name} — FX print: '+('ready' if index in self.engine.wet else 'not prepared'))
        self.refresh_fx_list()
        self.rack_eq.blockSignals(True)
        self.rack_eq.setChecked(self.rows[index]['eq'].isChecked())
        self.rack_eq.setEnabled(index in self.engine.wet)
        self.rack_eq.blockSignals(False)

    def rack_toggle_eq(self,enabled):
        if self.selected_track is not None and self.selected_track<len(self.rows):
            self.rows[self.selected_track]['eq'].setChecked(enabled)

    def master_changed(self,value):
        db=value/10
        self.engine.set_master_gain(db)
        self.master_readout.setText(f'{db:+.1f} dB (plus −12 dB de sécurité)')

    def states(self):
        return [{**r['entry'],'solo':r['solo'].isChecked(),'mute':r['mute'].isChecked(),
                 'gain_db':r['gain'].value(),'pan':r['pan'].value(),'eq':r['eq'].isChecked()} for r in self.rows]

    def update_states(self,*args):
        if not self.rows:return
        current=self.states()
        for i,s in enumerate(current):
            if s['eq'] and i not in self.engine.wet:
                # No fake wet playback: warn and refuse until Pro-Q rendering is ready.
                current[i]['eq']=False
                w=self.rows[i]['eq'];w.blockSignals(True);w.setChecked(False);w.blockSignals(False)
                self.status.setText('FX not prepared for this track. Click Prepare selected FX chains first.')
        self.engine.update_states(current)
        if self.selected_track is not None:self.select_track(self.selected_track)

    def toggle_play(self):
        if not self._require_stems('la lecture'):return
        try:
            if self.engine.playing:self.engine.pause()
            else:self.engine.play()
        except Exception as e:QMessageBox.warning(self,'Playback failed',str(e))
    def stop(self):self.engine.stop()
    def seek_to(self):
        if self.engine.duration_ms:self.engine.seek(round(self.seek.value()*self.engine.duration_ms/1000))
    def refresh_transport(self):
        duration=self.engine.duration_ms;pos=self.engine.position_ms
        self.time.setText(f'{pos//60000:02d}:{pos//1000%60:02d} / {duration//60000:02d}:{duration//1000%60:02d}')
        if duration and not self.seek.isSliderDown():self.seek.setValue(min(1000,round(1000*pos/duration)))
        self.play.setText('❚❚ Pause' if self.engine.playing else '▶ Play')
        for row,db in zip(self.rows,self.engine.meter_levels()):
            row['meter'].setValue(max(0,min(90,round(db+90))))
        if self.engine.peak>=1.0:self.status.setText('WARNING: monitoring clipped; reduce stem gains or master fader.')
    def all_tracks(self):
        for r in self.rows:
            for key in ('solo','mute'):
                w=r[key];w.blockSignals(True);w.setChecked(False);w.blockSignals(False)
        self.update_states()

    def save_config(self):
        if not self._require_stems('la sauvegarde du mix'):return False
        config={**self.config,'tracks':[{k:v for k,v in s.items() if k!='solo'} for s in self.states()]}
        path=self._config_path()
        try:
            # A restored manual selection can precede creation of this project folder.
            if self._selected_files_mode:
                path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(config,indent=2,ensure_ascii=False),encoding='utf-8')
            self.status.setText(f'Configuration enregistrée : {path}')
            return True
        except OSError as exc:
            if self._guided_pipeline:
                self._stop_guided_production(f'Auto Produce arrêté : {exc}')
            QMessageBox.warning(self,'Save error',str(exc))
            return False

    def cache_path(self):
        if self._selected_files_mode and self.config:
            import hashlib
            key='\n'.join(str(x['file']) for x in self.config['tracks'])
            digest=hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]
            return self.root/'sound'/'output'/'stem_plus'/f'manual-{digest}'
        return self.root/'sound'/'output'/'stem_plus'/Path(self.folder.text().strip()).name
    def _job(self,script,args,kind):
        if self.job.state()!=QProcess.NotRunning:
            return
        if not script.is_file():
            message = (f'Script de traitement introuvable :\n{script}\n\n'
                       'Le patch ne semble pas complètement installé.\n'
                       'Copie également le dossier scripts/ fourni avec cette version.')
            self.status.setText('Traitement annulé : script manquant.')
            self.log.appendPlainText(message)
            QMessageBox.critical(self, 'Composant de traitement manquant', message)
            if self._guided_pipeline:self._stop_guided_production('Auto Produce arrêté : script manquant.')
            return
        self._kind=kind
        self._set_busy(True, f'Rendu audio en cours : {script.name} — progression non estimable')
        self.job.start(sys.executable,['-u',str(script),*args])
        self.status.setText(f'{kind} en cours…')
        self.refresh_action_availability()

    def prepare_eq(self):
        if not self._require_stems('la préparation EQ'):return
        if not self.save_config():
            return
        if not any(s['eq'] for s in self.states()):
            # EQ can't be toggled before prepared; prepare selected rows, default all.
            msg=QMessageBox.question(self,'Prepare EQ','Préparer le traitement Pro-Q pour toutes les pistes? (Les fichiers originaux restent intacts.)')
            if msg!=QMessageBox.Yes:return
            config=json.loads(self._config_path().read_text(encoding='utf-8'))
            for row in config['tracks']:row['eq']=True
            self._config_path().write_text(json.dumps(config,indent=2),encoding='utf-8')
        chosen=selected_proq4(self.root/'settings'/'vst_roles.json')
        if chosen is None:
            QMessageBox.warning(self,'Plugin configuration required','Choose FabFilter Pro-Q 4 as Corrective EQ under Plugins → Configure installed VST3 plugins. Other EQs are not yet supported for parameter automation.')
            return
        self._job(self.root/'scripts'/'stem_plus_prepare.py',
            ['--folder',self.folder.text().strip(),'--config',str(self._config_path()),'--out',str(self.cache_path()),'--plugin',str(chosen)],'prepare')

    def export_to_mastering(self):
        """Export a premix in sound/source for the existing stereo mastering picker.
        The final master must still pass the later distribution QC stage.
        """
        if not self._require_stems('l’export vers le mastering'):return
        if not self.save_config():
            return
        dest=self.root/'sound'/'source'/f'{"Selected-Stems" if self._selected_files_mode else Path(self.folder.text().strip()).name}-STEM-premix.wav'
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            answer=QMessageBox.question(self,'Overwrite premix?',f'{dest.name} exists. Replace this premix?')
            if answer!=QMessageBox.Yes:return
        self.last_export=dest
        self._job(self.root/'scripts'/'stem_mix.py',
            ['--folder',self.folder.text().strip(),'--config',str(self._config_path()),'--output',str(dest),'--prepared',str(self.cache_path()/'prepared.json')],'send')

    def render_mix(self):
        if not self._require_stems('le rendu du mix'):return
        if not self.save_config():
            return
        self._job(self.root/'scripts'/'stem_mix.py',['--folder',self.folder.text().strip(),'--config',str(self._config_path()),'--prepared',str(self.cache_path()/'prepared.json')],'mix')

    def _find_comparison_report(self):
        """Reuse the newest valid Auto Mix session, including after app restart."""
        if self._latest_comparison and Path(self._latest_comparison).is_file():
            return Path(self._latest_comparison)
        if not self.config:
            return None
        root = self.cache_path() / 'auto_mix'
        if not root.is_dir():
            return None
        for report in sorted(root.glob('session-*/comparison.json'),
                             key=lambda path: path.stat().st_mtime, reverse=True):
            try:
                from .mix_comparison import load_comparison
                load_comparison(report)
                return report
            except (ValueError, FileNotFoundError, OSError, ImportError):
                continue
        return None

    def _on_auto_analysis_finished(self, successful, details):
        """Finish Auto Studio when analysis and optional LUFS measurement settle."""
        if successful:
            self._auto_step('Terminé — trois mixages prêts, analyse terminée. Tu peux les comparer.')
        else:
            self._auto_step('Terminé — trois mixages prêts. Analyse partielle : ' + str(details)[:200])
        self._set_busy(False)
        self.refresh_action_availability()

    def open_auto_mix_comparison(self, report=None, auto_analyze=False):
        candidate = report if isinstance(report, (dict, Path)) else self._find_comparison_report()
        if candidate is None:
            QMessageBox.information(self, 'Aucune comparaison',
                'Génère les trois variantes avec Auto Mix avant de les comparer.')
            return
        try:
            from .mix_compare_ui import MixCompareDialog
            previous = self._compare_window
            if previous is not None and previous.isVisible():
                previous.raise_()
                previous.activateWindow()
                return
            player = MixCompareDialog(candidate, self)
            self._compare_window = player  # Keep Qt dialog alive while it is visible.
            player.finished.connect(lambda *_: setattr(self, '_compare_window', None))
            if auto_analyze:
                player.automaticAnalysisFinished.connect(self._on_auto_analysis_finished)
            # Non-blocking: the QProcess.finished handler must return so the
            # main render progress bar and busy state can clear immediately.
            player.show()
            player.raise_()
            player.activateWindow()
            if auto_analyze:
                QTimer.singleShot(300, player.start_automatic_analysis)
        except Exception as exc:
            self._set_busy(False)
            if auto_analyze:
                self._auto_step('Mixages prêts — analyse non lancée : ' + str(exc))
            QMessageBox.warning(self, 'Comparateur indisponible', str(exc))

    def auto_mix_candidates(self):
        """Render three conservative gain candidates; never alter active mixer settings."""
        if not self._require_stems('la comparaison Auto Mix'):return
        if not self.save_config():
            return
        approval=QMessageBox.question(self,'Auto Mix — 3 versions',
            'Préparer Balanced, Vocal Focus et Punchy ?\n\n'
            'Les FX déjà préparés seront réutilisés si activés. '
            'Les stems originaux et les réglages actuels resteront inchangés.\n\n'
            'Ce sont des variantes de niveaux, pas encore une optimisation par écoute IA.')
        if approval!=QMessageBox.Yes:return
        self._job(self.root/'scripts'/'auto_mix_candidates.py',
                  ['--folder',self.folder.text().strip(),'--config',str(self._config_path()),
                   '--prepared',str(self.cache_path()/'prepared.json'),
                   '--out',str(self.cache_path()/'auto_mix')],'auto_mix')

    def job_done(self, code, _status):
        if self._guided_cancelled:
            self._guided_cancelled=False
            self.log.appendPlainText('AUTO STUDIO · Processus de rendu arrêté par l’utilisateur.')
            self._set_busy(False)
            self.refresh_action_availability()
            return
        self.refresh_action_availability()
        raw = bytes(self.job.readAllStandardOutput()).decode('utf-8', errors='replace').strip()
        if raw:
            self.log.appendPlainText(raw[-5000:])
        try:
            response = self._parse_job_result(raw, code)
            if self._kind in ('prepare','fx_prepare'):
                for key,path in response['processed'].items():
                    idx=int(key)
                    self.engine.set_processed(idx,Path(path))
                    if self._guided_pipeline and 0 <= idx < len(self.rows):
                        self.rows[idx]['entry']['eq']=True
                        checkbox=self.rows[idx]['eq']
                        checkbox.blockSignals(True)
                        checkbox.setChecked(True)
                        checkbox.blockSignals(False)
                if self._guided_pipeline:
                    if not self.save_config():
                        return
                if self.selected_track is not None:
                    self.select_track(self.selected_track)
                self.status.setText('FX préparés. Utilise FX ON pour comparer Dry/Wet.')
                if self._guided_pipeline:
                    QTimer.singleShot(0,self._guided_render_mix)
            elif self._kind == 'auto_mix':
                folder=Path(response['folder'])
                self._latest_comparison=folder/'comparison.json'
                self.status.setText(f'Auto Mix : 3 variantes disponibles dans le comparateur intégré.')
                self.log.appendPlainText('Versions : '+', '.join(f'{name}: {info["wav"]}' for name,info in response['variants'].items()))
                self.refresh_action_availability()
                # Open the A/B/C player immediately; do not send users to Explorer.
                guided=self._guided_pipeline
                self._guided_pipeline=False
                self._hide_guided_progress()
                # The render is already complete: stop its busy animation before
                # starting the independent comparison / AI evaluation.
                self._set_busy(False)
                self._auto_step('Étape 4/4 — Mixages prêts. Analyse DSP / Hermes / LUFS en cours…' if guided else 'Auto Mix terminé — comparaison disponible.')
                if getattr(self, 'guided_frontend', False):
                    self.productionFinished.emit(str(self._latest_comparison))
                else:
                    QTimer.singleShot(0, lambda report=self._latest_comparison, guided=guided:
                                      self.open_auto_mix_comparison(report, auto_analyze=guided))
            elif self._kind == 'send':
                self.status.setText('Prémix exporté : ' + Path(response['output']).name)
                self.sourceExported.emit(response['output'])
            else:
                self.status.setText('Mix exporté : ' + response['output'])
        except Exception as exc:
            if self._guided_pipeline:self._stop_guided_production('Auto Produce arrêté : erreur de rendu.')
            message = str(exc)
            self.status.setText('Erreur de traitement — consulte le journal ci-dessous.')
            self.log.appendPlainText('ÉCHEC : ' + message)
            QMessageBox.warning(self, 'Traitement audio impossible', message)
        finally:
            self.refresh_action_availability()

    @staticmethod
    def _parse_job_result(raw: str, exit_code: int) -> dict:
        """Translate missing/malformed subprocess output into useful diagnostics."""
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                response = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(response, dict) and 'status' in response:
                if exit_code or response['status'] != 'ok':
                    raise RuntimeError(str(response.get('error') or f'Code de sortie {exit_code}'))
                return response
        detail = '\n'.join(lines[-5:])[-1200:] if lines else '(aucune sortie du script)'
        raise RuntimeError(f'Le script a échoué (code {exit_code}) sans résultat JSON valide.\n\n{detail}')


    def _fx_chain(self):
        if self.selected_track is None or not self.rows: return []
        return self.rows[self.selected_track]['entry'].setdefault('fx_chain',[])

    def refresh_fx_list(self):
        self.fx_list.clear()
        for step in self._fx_chain():
            self.fx_list.addItem(('● ' if step.get('enabled',True) else '○ ') + step.get('role','fx') + ' — ' + Path(step.get('plugin','')).stem + (' [state]' if step.get('state_file') else ''))

    def _sync_chain(self):
        self.refresh_fx_list()
        # Any change makes the existing cached WAV stale; never claim it matches.
        i=self.selected_track
        if i is not None and i in self.engine.wet:
            with self.engine.lock:
                self.engine.wet.pop(i,None)
            w=self.rows[i]['eq'];w.setChecked(False)
        self.save_config()

    def fx_add(self):
        if not self._require_stems('l’ajout d’un FX'):return
        if self.selected_track is None:return
        role=self.fx_role.currentData()
        settings=read_settings(self.root/'settings'/'vst_roles.json')
        file=settings.get('roles',{}).get(role,'')
        if not file or not Path(file).exists():
            QMessageBox.warning(self,'Missing VST3',f'Configure the {role} plugin in Plugins → Configure installed VST3 plugins first.')
            return
        self._fx_chain().append({'role':role,'plugin':file,'enabled':True,'state_file':''})
        self._sync_chain()

    def fx_remove(self):
        n=self.fx_list.currentRow();chain=self._fx_chain()
        if 0<=n<len(chain):chain.pop(n);self._sync_chain()

    def _move_fx(self,direction):
        n=self.fx_list.currentRow();chain=self._fx_chain();other=n+direction
        if 0<=n<len(chain) and 0<=other<len(chain):
            chain[n],chain[other]=chain[other],chain[n]
            self._sync_chain();self.fx_list.setCurrentRow(other)

    def fx_up(self):self._move_fx(-1)
    def fx_down(self):self._move_fx(1)

    def fx_bypass(self):
        n=self.fx_list.currentRow();chain=self._fx_chain()
        if 0<=n<len(chain):
            chain[n]['enabled']=not chain[n].get('enabled',True)
            self._sync_chain()

    def _selected_fx_step(self):
        n=self.fx_list.currentRow()
        chain=self._fx_chain()
        return chain[n] if 0<=n<len(chain) else None

    def fx_load_state(self):
        """Load a native JUCE host state file, not a Cubase/FabFilter preset."""
        step=self._selected_fx_step()
        if step is None:return
        name,_=QFileDialog.getOpenFileName(self,'Select JUCE VST3 plugin state',str(self.root),'Host state (*.state *.bin);;All files (*)')
        if not name:return
        if not Path(name).is_file():return
        step['state_file']=str(Path(name).resolve())
        self._sync_chain()
        self.status.setText('Plugin state selected. Re-prepare FX to hear the new state. Confirm the state belongs to this plugin.')

    def fx_clear_state(self):
        step=self._selected_fx_step()
        if step is None:return
        step['state_file']=''
        self._sync_chain()

    def fx_inspect(self):
        step=self._selected_fx_step()
        if step is None:return
        from .host import run_host
        host=self.root/'native'/'build'/'mastering-host_artefacts'/'Release'/'mastering-host.exe'
        try:
            result=run_host(host,'inspect',plugin=Path(step['plugin']))
            parameters=result.get('parameters',[])
            interesting=[f"{p.get('index')}: {p.get('name')} = {p.get('text','')}" for p in parameters if p.get('automatable') and p.get('name') not in ('MIDI CC','Internal')]
            self.log.appendPlainText(f"FX INSPECT: {Path(step['plugin']).name} | {len(interesting)} automatable params | latency={result.get('latency_samples','?')} samples")
            self.log.appendPlainText('\n'.join(interesting[:15]))
            self.status.setText('Plugin inspected. Full details require native editor support in a later release.')
        except Exception as exc:
            QMessageBox.warning(self,'Plugin inspect failed',str(exc))

    def fx_edit_parameters(self):
        step=self._selected_fx_step()
        if step is None:return
        from .host import run_host
        from .plugin_parameters_ui import ParameterEditorDialog
        host=self.root/'native'/'build'/'mastering-host_artefacts'/'Release'/'mastering-host.exe'
        try:
            result=run_host(host,'inspect',plugin=Path(step['plugin']))
            dialog=ParameterEditorDialog(Path(step['plugin']).stem,result.get('parameters',[]),
                                         step.get('parameter_overrides',[]),self)
            if dialog.exec()==dialog.Accepted:
                step['parameter_overrides']=dialog.overrides()
                self._sync_chain()
                self.status.setText('Parameter changes saved. Click Prepare selected FX chains to hear them.')
        except Exception as exc:
            QMessageBox.warning(self,'Parameter editor error',str(exc))

    def configure_ai_model(self):
        from .ai_settings_ui import AISettingsDialog
        AISettingsDialog(self.root, self).exec()

    def _start_ai_review(self, proposals, model):
        if self._ai_thread is not None:
            QMessageBox.information(self,'AI busy','Une analyse IA est déjà en cours.');return
        self.fx_suggest_btn.setEnabled(False)
        self.ai_model_btn.setEnabled(False)
        self.status.setText(f'IA locale {model} : révision des chaînes FX en cours…')
        self._set_busy(True, f'Analyse IA en cours : {model} — attente de réponse Ollama')
        thread=QThread(self)
        worker=_OllamaReviewWorker(proposals, model)
        worker.moveToThread(thread)
        self._ai_thread=thread;self._ai_worker=worker
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ai_review_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup_ai_thread)
        thread.start()
        self.refresh_action_availability()

    @Slot(object,object)
    def _on_ai_review_finished(self, proposals, error):
        if self._guided_cancelled:
            self.log.appendPlainText('AUTO STUDIO · Réponse Ollama ignorée après annulation.')
            return
        if self._guided_pipeline:
            self._hide_guided_progress()  # Allow approval and any warnings.
        self.fx_suggest_btn.setEnabled(True)
        self.ai_model_btn.setEnabled(True)
        if error:
            self.log.appendPlainText(f'IA indisponible : {error} — suggestions techniques conservées.')
            QMessageBox.warning(self,'AI review unavailable',
                f'Les suggestions techniques sont conservées.\n\n{error}')
        else:
            self.log.appendPlainText('Révision Ollama terminée. Aucun fichier audio envoyé au modèle.')
        self._show_fx_proposals(proposals)

    @Slot()
    def _cleanup_ai_thread(self):
        if self._ai_thread is not None:
            self._ai_thread.deleteLater()
        self._ai_thread=None
        self._ai_worker=None
        self._set_busy(False)
        self.refresh_action_availability()

    def fx_suggest_all(self):
        """Analyze every track and present proposals before modifying any chain."""
        if not self._require_stems('les suggestions FX'):return
        from .auto_fx import suggest_project
        import tempfile
        from .stem_mixer import decode_audio
        import json
        settings=read_settings(self.root/'settings'/'vst_roles.json')
        roles=settings.get('roles',{})
        try:
            # Analyze decoded temporary WAVs for MP3 stems too; never touch source files.
            with tempfile.TemporaryDirectory(prefix='aml-suggest-') as tmp:
                inputs=[]
                for r in self.rows:
                    entry=dict(r['entry'])
                    entry['file']=str(decode_audio(Path(entry['file']),Path(tmp)))
                    inputs.append(entry)
                proposals=suggest_project(inputs,roles)
                for i,p in enumerate(proposals):
                    p['file']=str(self.rows[i]['entry']['file'])
                    p['name']=Path(p['file']).stem
        except Exception as exc:
            if self._guided_pipeline:self._stop_guided_production(f'Auto Produce arrêté : analyse FX impossible — {exc}')
            QMessageBox.warning(self,'FX suggestion failed',str(exc));return
        if self.ai_review_check.isChecked():
            try:
                from .ai_settings_ui import read_ai_preferences
                model=read_ai_preferences(self.root)['model']
                self._start_ai_review(proposals,model)
            except Exception as exc:
                QMessageBox.warning(self,'AI configuration issue',str(exc))
                self._show_fx_proposals(proposals)
            return
        self._show_fx_proposals(proposals)

    def _show_fx_proposals(self, proposals):
        """Display approval and keep final plugin application on the GUI thread."""
        if self._guided_cancelled:return
        if self._guided_pipeline:self._hide_guided_progress()
        if not any(p['fx_chain'] for p in proposals):
            if self._guided_pipeline:
                self.log.appendPlainText('Aucun VST compatible configuré : rendu des trois mixes sans nouvelle chaîne FX.')
                self._guided_render_mix()
                return
            QMessageBox.information(self,'No suggestions','Aucun VST compatible configuré pour ces stems. Configure tes rôles VST dans Plugins.');return
        # Generate actual conservative Pro-Q 4 band settings only when our verified
        # adapter and the plugin parameter names agree. Do not guess other VST maps.
        from .host import run_host
        from .proq4 import build_changes
        inspected={}
        host=self.root/'native'/'build'/'mastering-host_artefacts'/'Release'/'mastering-host.exe'
        for p in proposals:
            for step in p['fx_chain']:
                plugin=Path(step['plugin'])
                if step['role']!='corrective_eq' or 'pro-q 4' not in plugin.stem.lower() or not p['eq_moves']:
                    continue
                try:
                    if str(plugin) not in inspected:
                        inspected[str(plugin)]=run_host(host,'inspect',plugin=plugin)
                    changes=build_changes(inspected[str(plugin)],p['eq_moves'],max_bands=3)
                    step['parameter_overrides']=[{'index':i,'value':v} for i,v in changes]
                    p['reasons'].append('Pro-Q 4 : corrections douces préparées (max 0,7 dB), à valider à l’oreille')
                except Exception as exc:
                    p['warnings'].append(f'Automatisation Pro-Q non disponible : {exc}')
        # A visible per-stem approval table replaces the old all-bypassed-only flow.
        from .fx_bulk_apply import apply_proposals
        dialog=QDialog(self);dialog.setWindowTitle('Auto FX — Review and apply to STEM+')
        dialog.resize(800,550);layout=QVBoxLayout(dialog)
        note=QLabel('Choisis les pistes à traiter. Les recommandations sont indicatives, et les effets déjà configurés ne seront pas modifiés.\n'
                    '« Appliquer + préparer » active les nouveaux FX et lance leur rendu hors ligne; la lecture Dry/Wet reste disponible.')
        note.setWordWrap(True);layout.addWidget(note)
        choices=[]
        pane=QScrollArea();pane.setWidgetResizable(True);inner=QWidget();inner_lay=QVBoxLayout(inner)
        for p in proposals:
            if not p['fx_chain']:continue
            name=p['name'];chain=' → '.join(Path(step['plugin']).stem for step in p['fx_chain'])
            c=QCheckBox(f'{name}  |  {chain}');c.setChecked(True);inner_lay.addWidget(c)
            why='; '.join(p.get('reasons',[])+p.get('warnings',[]))
            hint=QLabel(why);hint.setWordWrap(True);hint.setStyleSheet('color:#a6abc1;padding-left:18px;')
            inner_lay.addWidget(hint);choices.append((p,c))
        inner_lay.addStretch();pane.setWidget(inner);layout.addWidget(pane)
        controls=QHBoxLayout()
        select_all=QPushButton('Tout sélectionner');select_all.clicked.connect(lambda: [c.setChecked(True) for _,c in choices]);controls.addWidget(select_all)
        deselect=QPushButton('Tout désélectionner');deselect.clicked.connect(lambda: [c.setChecked(False) for _,c in choices]);controls.addWidget(deselect)
        layout.addLayout(controls)
        buttons=QHBoxLayout()
        bypass_btn=QPushButton('Ajouter en bypass seulement')
        active_btn=QPushButton('✓ Appliquer + préparer toutes les pistes sélectionnées')
        cancel_btn=QPushButton('Annuler')
        buttons.addWidget(bypass_btn);buttons.addWidget(active_btn);buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)
        mode={'value':None}
        def accept(mode_name):mode['value']=mode_name;dialog.accept()
        bypass_btn.clicked.connect(lambda:accept('bypass'))
        active_btn.clicked.connect(lambda:accept('prepare'))
        cancel_btn.clicked.connect(dialog.reject)
        if dialog.exec()!=QDialog.Accepted:
            if self._guided_pipeline:self._stop_guided_production('Auto Produce annulé — FX non approuvés.')
            return
        chosen=[p for p,c in choices if c.isChecked()]
        if not chosen:
            if self._guided_pipeline:self._stop_guided_production('Auto Produce annulé — aucune piste approuvée.')
            QMessageBox.information(self,'No selected stems','Aucune piste sélectionnée.');return
        # Do not change pre-existing user effects, including ones currently bypassed.
        result=apply_proposals([r['entry'] for r in self.rows],chosen,enable_new=(mode['value']=='prepare'))
        if not result['added']:
            if self._guided_pipeline:
                self._auto_step('Étape 2/4 — Réutilisation des FX déjà présents…')
                self._guided_prepare_or_mix()
                return
            QMessageBox.information(self,'FX already present',
                'Les FX proposés sont déjà présents. Les chaînes existantes ne sont pas activées automatiquement.');return
        with self.engine.lock:self.engine.wet.clear()
        for row in self.rows:
            widget=row['eq'];widget.blockSignals(True);widget.setChecked(False);widget.blockSignals(False)
        self.update_states()
        if not self.save_config():
            return
        self.refresh_fx_list()
        self.log.appendPlainText(f"Auto FX: {result['added']} nouveaux FX sur {len(result['tracks_changed'])} pistes, mode {mode['value']}. Config saved. Original WAVs untouched.")
        if self._guided_pipeline:
            if mode['value']=='prepare':
                self._guided_prepare_or_mix()
            else:
                self._stop_guided_production('Auto Produce arrêté — les FX ont été ajoutés en bypass. Relance pour préparer.')
        elif mode['value']=='prepare':
            self.prepare_fx()
        else:
            self.status.setText(f"{result['added']} FX ajoutés en bypass. Utilise Edit parameters ou Bypass FX pour les activer.")

    def _guided_prepare_or_mix(self):
        if any(any(step.get('enabled', True) for step in r['entry'].get('fx_chain',[])) for r in self.rows):
            self._auto_step('Étape 2/4 — Préparation VST3 hors ligne…')
            if not self.save_config():
                return
            self._job(self.root/'scripts'/'stem_fx_prepare.py',
                      ['--folder',self.folder.text().strip(),'--config',str(self._config_path()),
                       '--out',str(self.cache_path())], 'fx_prepare')
            if self.job.state()==QProcess.NotRunning:
                self._stop_guided_production('Auto Produce arrêté : préparation FX non démarrée.')
        else:
            self._guided_render_mix()

    def prepare_fx(self):
        if not self._require_stems('la préparation des FX'):return
        if not self.save_config():
            return
        if not any(any(step.get('enabled',True) for step in r['entry'].get('fx_chain',[])) for r in self.rows):
            QMessageBox.information(self,'No FX','Add at least one active VST3 to a track first.');return
        self._job(self.root/'scripts'/'stem_fx_prepare.py',
                  ['--folder',self.folder.text().strip(),'--config',str(self._config_path()),
                   '--out',str(self.cache_path())], 'fx_prepare')

    def shutdown(self):self.engine.close()
