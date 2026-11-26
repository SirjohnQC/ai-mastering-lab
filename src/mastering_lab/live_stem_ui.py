"""FRANKENSTEM v0.27.0 experimental real-time multistem audition UI.

QProcess owns a separate JUCE audio-device process. Audio FX changes send small
JSON commands, never rendering preview WAVs. Existing album export is unchanged.
"""
from __future__ import annotations

import json
from concurrent.futures import Future
from pathlib import Path
from threading import Event, Thread

from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QSlider, QCheckBox, QMessageBox, QDialogButtonBox,
)

from .stem_mixer import config_template
from .stem_saturation import validated_selections, suggestions
from .live_engine_startup import locate_engine
from .version import APP_VERSION


def _scan_whistles(path, model, cancelled, result):
    try:
        from .vocal_whistle import scan_vocal_whistles

        markers = scan_vocal_whistles(path, cancelled=cancelled.is_set)
        note = ''
        if model and not cancelled.is_set():
            try:
                from .spectral_vision import review_vocal_whistles
                review = review_vocal_whistles(path, markers, model=model)
                note = ' '.join(review['observations'] + review['limits'])[:550]
            except Exception as exc:
                note = 'Vision Ollama indisponible · ' + str(exc)[:170]
        result.set_result((markers, note))
    except Exception as exc:
        result.set_exception(exc)


def find_live_engine(root):
    return locate_engine(root)


class LiveStemDialog(QDialog):
    def __init__(self, root, folder, saved=None, parent=None):
        super().__init__(parent)
        self.root=Path(root)
        self.config=config_template(Path(folder))
        self.rows=suggestions(self.config)
        if len(self.rows)<2 or len(self.rows)>32:
            raise ValueError('Live Engine nécessite 2 à 32 stems.')
        for item in self.rows:
            if Path(item['file']).suffix.lower()!='.wav':
                raise ValueError('Live Engine v0.27.0 accepte uniquement les stems WAV.')
        self.saved=validated_selections(self.config,saved)
        self.active=0
        self.duration=0.
        self.seek_active=False
        self.ready=False
        self._startup_phase='pending'
        self._last_native_error=''
        self._forced_timeout=False
        self._closing_engine=False
        self.stdout=b''
        self._loading=False
        self.output=None
        self.whistle_supported = False
        self.whistle_results = {}
        self.whistle_job = None
        self.whistle_cancel = Event()
        self.setWindowTitle(f'FRANKENSTEM · Live Stem Lab v{APP_VERSION}')
        self.setMinimumWidth(690)
        v=QVBoxLayout(self)
        self.state=QLabel('Initialisation du moteur JUCE…')
        self.state.setWordWrap(True)
        v.addWidget(self.state)
        transport=QHBoxLayout()
        self.play=QPushButton('▶ Play')
        self.pause=QPushButton('Ⅱ Pause')
        self.stop=QPushButton('■ Stop')
        for widget,cmd in ((self.play,'play'),(self.pause,'pause'),(self.stop,'stop')):
            widget.clicked.connect(lambda _,c=cmd:self._send({'cmd':c}))
            transport.addWidget(widget)
        v.addLayout(transport)
        self.position=QSlider(Qt.Horizontal)
        self.position.setRange(0,1000)
        self.position.sliderPressed.connect(lambda:setattr(self,'seek_active',True))
        self.position.sliderReleased.connect(self._seek)
        v.addWidget(self.position)
        self.time=QLabel('00:00 / 00:00')
        v.addWidget(self.time)
        choose=QHBoxLayout()
        choose.addWidget(QLabel('Stem'))
        self.stem_picker=QComboBox()
        for row in self.rows: self.stem_picker.addItem(Path(row['file']).name)
        self.stem_picker.currentIndexChanged.connect(self._choose_stem)
        choose.addWidget(self.stem_picker,1)
        v.addLayout(choose)
        self.effect=QComboBox()
        for style,label in (('tape','Tape'),('tube','Tube'),('softclip','Soft Clip')):
            self.effect.addItem(label,style)
        v.addWidget(self.effect)
        self.drive=QSlider(Qt.Horizontal)
        self.drive.setRange(1,25)
        self.drive_title=QLabel()
        v.addWidget(self.drive_title)
        v.addWidget(self.drive)
        self.wet=QSlider(Qt.Horizontal)
        self.wet.setRange(0,40)
        self.wet_title=QLabel()
        v.addWidget(self.wet_title)
        v.addWidget(self.wet)
        flags=QHBoxLayout()
        self.enabled=QCheckBox('⚡ FX ON / Bypass')
        self.mute=QCheckBox('Mute')
        self.solo=QCheckBox('Solo')
        flags.addWidget(self.enabled)
        flags.addWidget(self.mute)
        flags.addWidget(self.solo)
        v.addLayout(flags)
        self.fx_note=QLabel(
            'Effets en mémoire, sans WAV temporaire. Les changements sont '
            'audibles pendant la lecture. Aucune exportation automatique.')
        self.fx_note.setWordWrap(True)
        v.addWidget(self.fx_note)
        self._add_whistle_controls(v)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('✓ Approuver FX pour Auto Produce')
        buttons.accepted.connect(self._approve)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.buttons=buttons
        self.controls=[self.play,self.pause,self.stop,self.position,
                       self.stem_picker,self.effect,self.drive,self.wet,
                       self.enabled,self.mute,self.solo]
        for item in self.controls: item.setEnabled(False)
        buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self.dirty={}
        self.effect.currentIndexChanged.connect(self._change_fx)
        self.drive.valueChanged.connect(self._change_fx)
        self.wet.valueChanged.connect(self._change_fx)
        self.enabled.toggled.connect(self._change_fx)
        self.mute.toggled.connect(self._change_fx)
        self.solo.toggled.connect(self._change_fx)
        self._choose_stem(0)
        self.process=QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(
            lambda *_:self._ended())
        self.watchdog=QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.setInterval(15000)
        self.watchdog.timeout.connect(self._startup_timeout)
        self.process.started.connect(self._started)
        self.poll=QTimer(self)
        self.poll.setInterval(700)
        self.poll.timeout.connect(lambda:self._send({'cmd':'status'}))
        executable=find_live_engine(self.root)
        if executable is None:
            self.state.setText(
                'Moteur non compilé. Exécute CMake avec la cible '
                'frankenstem-live (instructions dans docs/).')
            return
        self.process.setProgram(str(executable))
        self.process.setArguments(['--stems',*[row['file'] for row in self.rows]])
        self.state.setText('Chargement des stems dans le moteur JUCE…')
        self.process.start()
        self.watchdog.start()

    def _add_whistle_controls(self, layout):
        self.whistle_scan = QPushButton('Analyser les sifflements')
        self.whistle_scan.clicked.connect(self._start_whistle_scan)
        self.whistle_vision = QCheckBox('Vision Ollama')
        self.whistle_vision.setToolTip('Ajoute un avis visuel du modèle configuré dans les réglages IA.')
        row = QHBoxLayout()
        row.addWidget(self.whistle_scan)
        row.addWidget(self.whistle_vision)
        layout.addLayout(row)

        self.whistle_markers = QComboBox()
        self.whistle_markers.setAccessibleName('Marqueurs de sifflement')
        self.whistle_markers.currentIndexChanged.connect(self._select_whistle)
        self.whistle_jump = QPushButton('Aller au passage')
        self.whistle_jump.clicked.connect(self._jump_to_whistle)
        self.whistle_mode = QComboBox()
        self.whistle_mode.setAccessibleName('Écoute de la correction spectrale')
        for label, mode in (('A · Original', 'original'), ('B · Atténué', 'corrected'),
                            ('Résidu', 'residual')):
            self.whistle_mode.addItem(label, mode)
        self.whistle_mode.currentIndexChanged.connect(self._set_whistle_mode)
        row = QHBoxLayout()
        for widget in (self.whistle_markers, self.whistle_jump, self.whistle_mode):
            row.addWidget(widget)
        layout.addLayout(row)
        self.whistle_note = QLabel()
        self.whistle_note.setWordWrap(True)
        self.whistle_note.setTextFormat(Qt.PlainText)
        layout.addWidget(self.whistle_note)
        self.whistle_poll = QTimer(self)
        self.whistle_poll.setInterval(120)
        self.whistle_poll.timeout.connect(self._finish_whistle_scan)

    def _start_whistle_scan(self):
        if not self.whistle_supported or not self.ready or self.whistle_job is not None:
            return
        model = None
        if self.whistle_vision.isChecked():
            from .ai_settings_ui import read_ai_preferences
            model = read_ai_preferences(self.root)['vision_model']
        result = Future()
        self.whistle_job = self.active, result
        self._refresh_whistles()
        Thread(target=_scan_whistles,
               args=(self.rows[self.active]['file'], model, self.whistle_cancel, result),
               daemon=True).start()
        self.whistle_poll.start()

    def _finish_whistle_scan(self):
        index, result = self.whistle_job
        if not result.done():
            return
        self.whistle_poll.stop()
        self.whistle_job = None
        try:
            self.whistle_results[index] = result.result()
        except Exception as exc:
            self.whistle_results[index] = [], 'Analyse indisponible · ' + str(exc)[:250]
        self._refresh_whistles()

    def _refresh_whistles(self):
        available = self.ready and self.whistle_supported
        self.whistle_scan.setEnabled(available and self.whistle_job is None)
        self.whistle_vision.setEnabled(available and self.whistle_job is None)
        markers, note = self.whistle_results.get(self.active, ([], ''))
        self.whistle_markers.blockSignals(True)
        self.whistle_markers.clear()
        for marker in markers:
            self.whistle_markers.addItem(
                f"{marker['start']:.2f}–{marker['end']:.2f} s · {marker['hz']:.0f} Hz", marker)
        self.whistle_markers.blockSignals(False)
        has_marker = available and bool(markers)
        for widget in (self.whistle_markers, self.whistle_jump, self.whistle_mode):
            widget.setEnabled(has_marker)
        if self.ready and not available:
            status = 'Recompile frankenstem-live pour activer la correction spectrale.'
        elif self.whistle_job is not None:
            status = 'Analyse du stem en cours…'
        elif self.active in self.whistle_results:
            status = (f'{len(markers)} passage(s) à vérifier.' if markers else
                      'Aucune crête étroite persistante repérée.')
        else:
            status = 'Choisis un stem vocal pour chercher des sifflements. Écoute seulement.'
        self.whistle_note.setText(f'{status} {note}'.strip())
        self._select_whistle()

    def _select_whistle(self, *_):
        self.whistle_mode.blockSignals(True)
        self.whistle_mode.setCurrentIndex(0)
        self.whistle_mode.blockSignals(False)
        if self.whistle_supported:
            marker = self.whistle_markers.currentData()
            self._send({'cmd': 'whistle', **({'stem': self.active, **marker} if marker else {})})

    def _set_whistle_mode(self, *_):
        self._send({'cmd': 'whistle_mode', 'mode': self.whistle_mode.currentData()})

    def _jump_to_whistle(self):
        marker = self.whistle_markers.currentData()
        if marker:
            self._send({'cmd': 'seek', 'seconds': max(0, marker['start'] - 0.20)})

    def _started(self):
        self._startup_phase='started'
        self.state.setText('JUCE démarré · préparation des stems et du périphérique audio…')

    def _process_error(self,_error):
        # QProcess emits Crashed after *our own* watchdog calls kill().
        # Preserve the real timeout reason, not a fake spontaneous crash.
        if self._forced_timeout or self._closing_engine:
            return
        phase=self._startup_phase
        self._startup_phase='crash'
        self.watchdog.stop()
        self.state.setText(
            '⚠ JUCE s’est arrêté anormalement : '+self.process.errorString()+
            ' · Dernière étape : '+phase+
            ('. Détail : '+self._last_native_error[-180:]
             if self._last_native_error else '.'))


    def _startup_timeout(self):
        if self.ready:
            return
        phase=self._startup_phase
        self._startup_phase='timeout'
        self._forced_timeout=True
        self.state.setText(
            '⚠ Temps limite dépassé : JUCE n’a pas terminé la phase « '+phase+
            ' » en 15 secondes. FRANKENSTEM a fermé le processus bloqué. '
            'Ce n’est pas un crash natif confirmé.')
        self.fx_note.setText(
            'Live FX indisponible. Le mastering et les fichiers sources sont intacts. '
            'Consulte la sortie du terminal et reconstruis frankenstem-live.')
        if self.process.state()!=QProcess.NotRunning:
            self.process.kill()

    def _ended(self):
        was_ready=self.ready
        self.ready=False
        self.poll.stop()
        self.watchdog.stop()
        for item in self.controls: item.setEnabled(False)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self._refresh_whistles()
        if self._closing_engine or self._forced_timeout:
            return
        if was_ready and self.isVisible():
            self.state.setText(
                '⚠ Le moteur audio JUCE s’est fermé pendant la session. '
                'Code de sortie : '+str(self.process.exitCode()))
        elif self.isVisible() and self._startup_phase!='crash':
            self.state.setText(
                '⚠ JUCE s’est fermé avant d’être prêt (code '
                +str(self.process.exitCode())+'). '
                'Dernière étape : '+self._startup_phase+' · '
                +self._last_native_error[-180:])

    def _stderr(self):
        # Only show errors, never flood the UI from the audio callback.
        data=bytes(self.process.readAllStandardError()).decode('utf-8','replace')
        if data.strip():
            self._last_native_error=data[-350:]
            self.fx_note.setText(self._last_native_error)

    def _read(self):
        self.stdout+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self.stdout:
            line,self.stdout=self.stdout.split(b'\n',1)
            try: message=json.loads(line.decode('utf-8'))
            except (UnicodeDecodeError,json.JSONDecodeError): continue
            self._message(message)

    def _message(self,data):
        status=data.get('status')
        if status=='progress':
            self._startup_phase=str(data.get('message','Initialisation'))
            self.state.setText('JUCE · '+self._startup_phase+'…')
            # This watchdog measures stalled phases, not total song load time.
            self.watchdog.start()
            return
        if status=='ready':
            self.watchdog.stop()
            expected=len(self.rows)
            if len(data.get('stems',[]))!=expected:
                self.state.setText('Le moteur a chargé un nombre inattendu de stems.')
                self.process.kill()
                return
            self.ready=True
            self.whistle_supported = data.get('whistle_preview') is True
            self.state.setText('⚡ LIVE · JUCE · '+str(expected)+' stems synchronisés')
            for item in self.controls: item.setEnabled(True)
            self.buttons.button(QDialogButtonBox.Save).setEnabled(True)
            self.poll.start()
            self._push_all()
            self._refresh_whistles()
        elif status=='error':
            self.watchdog.stop()
            self.state.setText('⚠ '+str(data.get('message','Erreur audio')))
            self.fx_note.setText('Relance Live FX après correction du problème. Aucun fichier source modifié.')
        elif status=='ok':
            self.duration=float(data.get('duration_seconds',self.duration))
            seconds=float(data.get('seconds',0))
            if not self.seek_active and self.duration>0:
                self.position.blockSignals(True)
                self.position.setValue(round(seconds/self.duration*1000))
                self.position.blockSignals(False)
            def mmss(t):
                t=int(t)
                return f'{t//60:02}:{t%60:02}'
            self.time.setText(mmss(seconds)+' / '+mmss(self.duration))

    def _send(self,command):
        if self.ready and self.process.state()==QProcess.Running:
            self.process.write((json.dumps(command)+'\n').encode('utf-8'))

    def _seek(self):
        self.seek_active=False
        if self.duration>0:
            self._send({'cmd':'seek','seconds':self.duration*self.position.value()/1000})

    def _row_settings(self,index):
        row=self.rows[index]
        return self.dirty.get(index) or self.saved.get(row['file']) or {
            'enabled':False,'style':row['style'],'drive':row['drive'],
            'mix':row['mix'],'mute':False,'solo':False,
        }

    def _choose_stem(self,index):
        if index<0 or index>=len(self.rows): return
        self.active=index
        value=self._row_settings(index)
        self._loading=True
        self.effect.setCurrentIndex(max(0,self.effect.findData(value.get('style','tape'))))
        self.drive.setValue(round(value.get('drive',.6)*10))
        self.wet.setValue(round(value.get('mix',.12)*100))
        self.enabled.setChecked(value.get('enabled',False))
        self.mute.setChecked(value.get('mute',False))
        self.solo.setChecked(value.get('solo',False))
        self._loading=False
        self._update_numbers()
        self._refresh_whistles()

    def _update_numbers(self):
        self.drive_title.setText(f'Drive : {self.drive.value()/10:.1f}')
        self.wet_title.setText(f'Wet : {self.wet.value()}%')

    def _change_fx(self,*_):
        self._update_numbers()
        if self._loading: return
        value={'style':self.effect.currentData(),
               'drive':self.drive.value()/10,'mix':self.wet.value()/100,
               'enabled':self.enabled.isChecked(),
               'mute':self.mute.isChecked(),'solo':self.solo.isChecked()}
        self.dirty[self.active]=value
        self._send({'cmd':'set','stem':self.active,**value})

    def _push_all(self):
        for i in range(len(self.rows)):
            value=self._row_settings(i)
            self._send({'cmd':'set','stem':i,**value})

    def _approve(self):
        selection={}
        for i,row in enumerate(self.rows):
            item=self._row_settings(i)
            if item.get('enabled',False):
                selection[row['file']]={'enabled':True,'style':item['style'],
                     'drive':item['drive'],'mix':item['mix']}
        try:
            self.selection=validated_selections(self.config,selection)
        except ValueError as exc:
            QMessageBox.warning(self,'Live Stem FX',str(exc))
            return
        self.accept()

    def _shutdown(self):
        self._closing_engine=True
        self.whistle_cancel.set()
        self.whistle_poll.stop()
        self.poll.stop()
        self.watchdog.stop()
        if self.process.state()!=QProcess.NotRunning:
            self._send({'cmd':'stop'})
            self.process.write(b'{"cmd":"quit"}\n')
            self.process.waitForFinished(1200)
            if self.process.state()!=QProcess.NotRunning:
                self.process.kill()
                self.process.waitForFinished(800)

    def accept(self):
        self._shutdown()
        super().accept()

    def reject(self):
        self._shutdown()
        super().reject()

    def closeEvent(self,event):
        self._shutdown()
        super().closeEvent(event)
