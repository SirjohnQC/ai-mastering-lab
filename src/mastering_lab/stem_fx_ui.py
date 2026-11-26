"""FRANKENSTEM Stem Surgery: local analysis and Dry/Wet listening before opt-in.

The WAV source is NEVER replaced. Per-stem recommendations are rule-based;
the operator explicitly checks stems and approves the final FX settings.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt,QThread,Signal,QUrl
from PySide6.QtWidgets import (
    QDialog,QVBoxLayout,QHBoxLayout,QWidget,QLabel,QPushButton,QComboBox,
    QScrollArea,QCheckBox,QDoubleSpinBox,QDialogButtonBox,QMessageBox,QFrame
)
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput

from .stem_mixer import config_template
from .stem_saturation import suggestions,validated_selections


class FxScanWorker(QThread):
    advice=Signal(int,object)
    failed=Signal(int,str)
    complete=Signal()

    def __init__(self,config,parent=None):
        super().__init__(parent)
        self.config=config

    def run(self):
        from .stem_fx_advisor import inspect_stem_for_fx
        from .auto_mix_candidates import _group
        for i,row in enumerate(self.config['tracks']):
            if self.isInterruptionRequested():
                break
            try:
                self.advice.emit(i,inspect_stem_for_fx(row['file'],group=_group(row)))
            except Exception as exc:
                self.failed.emit(i,f'{type(exc).__name__}: {exc}')
        self.complete.emit()


class FxPreviewWorker(QThread):
    ready=Signal(object)
    failed=Signal(str)

    def __init__(self,path,cache,style,drive,mix,parent=None):
        super().__init__(parent)
        self.path=path
        self.cache=cache
        self.style=style
        self.drive=drive
        self.mix=mix

    def run(self):
        from .stem_fx_preview import prepare_stem_ab_preview
        try:
            self.ready.emit(prepare_stem_ab_preview(
                self.path,self.cache,style=self.style,
                drive=self.drive,mix=self.mix))
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class StemDryWetDialog(QDialog):
    """Preloaded aligned Dry/Wet audition. The original stem is never modified."""

    def __init__(self,source,style,drive,mix,cache,parent=None):
        super().__init__(parent)
        self.setWindowTitle('FRANKENSTEM · Dry / Wet · '+Path(source).name)
        self.setMinimumWidth(510)
        self.source=source
        self.cache=cache
        self.worker=None
        self.report=None
        self.active='dry'
        body=QVBoxLayout(self)
        self.status=QLabel('Création d’un extrait Dry/Wet aligné (max 18 secondes)…')
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        tabs=QHBoxLayout()
        self.dry_button=QPushButton('A · DRY')
        self.wet_button=QPushButton('B · WET')
        self.wet_button.setEnabled(False)
        tabs.addWidget(self.dry_button)
        tabs.addWidget(self.wet_button)
        body.addLayout(tabs)
        self.play_button=QPushButton('▶ Écouter / Pause')
        self.play_button.setEnabled(False)
        body.addWidget(self.play_button)
        self.active_label=QLabel('♫ EN ÉCOUTE : A · DRY')
        body.addWidget(self.active_label)
        self.time_label=QLabel('0:00')
        body.addWidget(self.time_label)
        warning=QLabel('Préécoute locale uniquement : niveau RMS rapproché, '
                       'pas de QC LUFS/True Peak sur ce stem.')
        warning.setWordWrap(True)
        body.addWidget(warning)
        self.a_audio=QAudioOutput(self)
        self.b_audio=QAudioOutput(self)
        self.a_player=QMediaPlayer(self)
        self.b_player=QMediaPlayer(self)
        self.a_player.setAudioOutput(self.a_audio)
        self.b_player.setAudioOutput(self.b_audio)
        self.a_audio.setVolume(1.)
        self.b_audio.setVolume(0.)
        self.a_player.positionChanged.connect(lambda p:self._position('dry',p))
        self.b_player.positionChanged.connect(lambda p:self._position('wet',p))
        self.dry_button.clicked.connect(lambda:self._switch('dry'))
        self.wet_button.clicked.connect(lambda:self._switch('wet'))
        self.play_button.clicked.connect(self._play)
        self._highlight()
        self.worker=FxPreviewWorker(source,cache,style,drive,mix,self)
        self.worker.ready.connect(self._ready)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _highlight(self):
        active='background:#6153b6;border:2px solid #baaaff;color:white;font-weight:700;'
        self.dry_button.setStyleSheet(active if self.active=='dry' else '')
        self.wet_button.setStyleSheet(active if self.active=='wet' else '')
        self.active_label.setText('♫ EN ÉCOUTE : '+(
            'A · DRY' if self.active=='dry' else 'B · WET'))

    def _ready(self,report):
        self.report=report
        self.a_player.setSource(QUrl.fromLocalFile(report['dry']))
        self.b_player.setSource(QUrl.fromLocalFile(report['wet']))
        self.play_button.setEnabled(True)
        self.wet_button.setEnabled(True)
        self.status.setText(
            f'Extrait {report["start_ms"]/1000:.1f}–'
            f'{(report["start_ms"]+report["duration_ms"])/1000:.1f}s · '
            f'{report["style"].title()} · Drive {report["drive"]:.2f} · '
            f'Wet {report["mix"]:.0%}. '
            'Choisis A ou B; aucun FX n’est approuvé automatiquement.')

    def _failed(self,message):
        self.status.setText('⚠ Préécoute impossible : '+message)

    def _finished(self):
        self.worker=None

    def _position(self,source,ms):
        if self.active==source:
            self.time_label.setText(f'{ms//60000}:{(ms//1000)%60:02d}')

    def _play(self):
        active=self.a_player if self.active=='dry' else self.b_player
        if active.playbackState()==QMediaPlayer.PlayingState:
            active.pause()
        else:
            active.play()

    def _switch(self,target):
        if target==self.active or self.report is None:
            return
        previous=self.a_player if self.active=='dry' else self.b_player
        following=self.a_player if target=='dry' else self.b_player
        pos=previous.position()
        playing=previous.playbackState()==QMediaPlayer.PlayingState
        following.setPosition(pos)
        if playing:
            # Already-preloaded WAV, no setSource on A/B switch.
            # Stop only the old decoder; the next will start at the same point.
            following.play()
            previous.pause()
        self.a_audio.setVolume(1. if target=='dry' else 0.)
        self.b_audio.setVolume(1. if target=='wet' else 0.)
        self.active=target
        self._highlight()
        self._position(target,pos)

    def closeEvent(self,event):
        if self.worker is not None:
            QMessageBox.information(self,'Préécoute en cours',
                'La préparation audio doit terminer avant de fermer la fenêtre.')
            event.ignore()
            return
        self.a_player.stop()
        self.b_player.stop()
        super().closeEvent(event)


class StemFxSurgeryDialog(QDialog):
    """Review DSP advice, audition a stem and approve individual FX choices."""

    def __init__(self,folder,saved,cache,parent=None):
        super().__init__(parent)
        self.config=config_template(Path(folder))
        self.saved=validated_selections(self.config,saved)
        self.cache=Path(cache)
        self.rows=[]
        self.worker=None
        self.setWindowTitle('FRANKENSTEM · Stem Inspector + FX Advisor')
        self.setMinimumWidth(820)
        self.resize(980,680)
        root=QVBoxLayout(self)
        intro=QLabel(
            'Mesures DSP locales · Les conseils ne détectent PAS l’origine IA. '
            'Tout est désactivé par défaut. Écoute Dry/Wet puis coche les pistes à traiter.')
        intro.setWordWrap(True)
        root.addWidget(intro)
        actions=QHBoxLayout()
        self.analyze_btn=QPushButton('✦ Analyser les stems et suggérer')
        self.analyze_btn.clicked.connect(self._analyze)
        actions.addWidget(self.analyze_btn)
        root.addLayout(actions)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        inner=QWidget()
        group=QVBoxLayout(inner)
        for hint in suggestions(self.config):
            path=hint['file']
            old=self.saved.get(path,{})
            card=QFrame()
            card.setStyleSheet(
                'QFrame {border:1px solid #41435c;border-radius:7px;padding:5px;}')
            v=QVBoxLayout(card)
            row=QHBoxLayout()
            check=QCheckBox(Path(path).name)
            check.setChecked(bool(old.get('enabled',False)))
            row.addWidget(check,1)
            style=QComboBox()
            for st in ('tape','tube','softclip'):
                style.addItem(st.title(),st)
            style.setCurrentIndex(max(0,style.findData(old.get('style',hint['style']))))
            row.addWidget(style)
            drive=QDoubleSpinBox()
            drive.setRange(.1,2.5)
            drive.setSingleStep(.1)
            drive.setValue(old.get('drive',hint['drive']))
            drive.setPrefix('Drive ')
            row.addWidget(drive)
            wet=QDoubleSpinBox()
            wet.setRange(1,40)
            wet.setValue(old.get('mix',hint['mix'])*100)
            wet.setSuffix('% Wet')
            row.addWidget(wet)
            preview=QPushButton('♫ Dry / Wet')
            row.addWidget(preview)
            v.addLayout(row)
            status=QLabel('Non analysé · Aucun FX appliqué par défaut.')
            status.setWordWrap(True)
            v.addWidget(status)
            group.addWidget(card)
            i=len(self.rows)
            self.rows.append({'file':path,'check':check,'style':style,
                              'drive':drive,'wet':wet,'status':status,
                              'preview':preview,'advice':None})
            preview.clicked.connect(lambda _,n=i:self._preview(n))
        group.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll,1)
        btn=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        btn.accepted.connect(self._approve)
        btn.rejected.connect(self.reject)
        root.addWidget(btn)
        self.analyze_btn.setEnabled(bool(self.rows))

    def _analyze(self):
        if self.worker is not None:return
        self.analyze_btn.setEnabled(False)
        for row in self.rows:
            row['status'].setText('Mesure locale en cours…')
        self.worker=FxScanWorker(self.config,self)
        self.worker.advice.connect(self._advice)
        self.worker.failed.connect(self._error)
        self.worker.finished.connect(self._scan_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _advice(self,index,advice):
        row=self.rows[index]
        row['advice']=advice
        stats=advice.get('metrics',{})
        label=('✦ Écoute suggérée' if advice['decision']=='audition'
               else '✓ Garder Dry par défaut')
        row['status'].setText(
            label+' · '+advice['reason']+
            f' | Peak échant. {stats.get("sampled_peak_dbfs","—")} dBFS · '
            f'Crest {stats.get("sampled_crest_db","—")} dB · '
            f'HF {stats.get("sampled_high_frequency_ratio","—")}')
        # Suggestions only update controls on tracks not previously approved.
        # NEVER silently check a box or enable treatment.
        if advice['suggestion'] and not row['check'].isChecked():
            proposed=advice['suggestion']
            row['style'].setCurrentIndex(max(0,row['style'].findData(proposed['style'])))
            row['drive'].setValue(proposed['drive'])
            row['wet'].setValue(proposed['mix']*100)

    def _error(self,index,message):
        self.rows[index]['status'].setText('⚠ Analyse impossible : '+message)

    def _scan_finished(self):
        self.worker=None
        self.analyze_btn.setEnabled(True)

    def _preview(self,index):
        if self.worker is not None:
            QMessageBox.information(self,'Analyse en cours',
                'Attends la fin de l’analyse avant d’ouvrir la préécoute.')
            return
        row=self.rows[index]
        view=StemDryWetDialog(
            row['file'],row['style'].currentData(),row['drive'].value(),
            round(row['wet'].value()/100,4),self.cache,self)
        view.exec()

    def _approve(self):
        if self.worker is not None:
            QMessageBox.information(self,'Analyse en cours',
                'Termine l’analyse avant de sauvegarder les choix.')
            return
        request={}
        for row in self.rows:
            if row['check'].isChecked():
                request[row['file']]={'enabled':True,'style':row['style'].currentData(),
                    'drive':row['drive'].value(),'mix':round(row['wet'].value()/100,4)}
        try:
            self.selection=validated_selections(self.config,request)
        except (ValueError,OSError) as exc:
            QMessageBox.warning(self,'Stem Surgery',str(exc))
            return
        self.accept()

    def closeEvent(self,event):
        if self.worker is not None:
            self.worker.requestInterruption()
            QMessageBox.information(self,'Analyse en cours',
                'Analyse annulée; referme la fenêtre une fois terminée.')
            event.ignore()
            return
        super().closeEvent(event)
