"""FRANKENSTEM v0.27.0 experimental real-time multistem audition UI.

QProcess owns a separate JUCE audio-device process. Audio FX changes send small
JSON commands, never rendering preview WAVs. Existing album export is unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QSlider, QCheckBox, QMessageBox, QDialogButtonBox,
)

from .stem_mixer import config_template
from .stem_saturation import validated_selections, suggestions


def find_live_engine(root):
    root=Path(root)
    candidates=(
        root/'native'/'build'/'frankenstem-live_artefacts'/'Release'/'frankenstem-live.exe',
        root/'native'/'build'/'frankenstem-live_artefacts'/'frankenstem-live.exe',
        root/'native'/'build'/'Release'/'frankenstem-live.exe',
    )
    return next((p for p in candidates if p.is_file()),None)


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
        self.stdout=b''
        self._loading=False
        self.output=None
        self.setWindowTitle('FRANKENSTEM · Live Stem Lab v0.27.0')
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
        self.process.errorOccurred.connect(
            lambda _error:self.state.setText('Erreur moteur JUCE : '+self.process.errorString()))
        self.process.finished.connect(
            lambda *_:self._ended())
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
        self.process.start()

    def _ended(self):
        was_ready=self.ready
        self.ready=False
        self.poll.stop()
        for item in self.controls: item.setEnabled(False)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        if was_ready and self.isVisible():
            self.state.setText(
                '⚠ Le moteur audio JUCE est fermé. '
                'Rouvre Live FX pour repartir une session propre.')

    def _stderr(self):
        # Only show errors, never flood the UI from the audio callback.
        data=bytes(self.process.readAllStandardError()).decode('utf-8','replace')
        if data.strip(): self.fx_note.setText(data[-350:])

    def _read(self):
        self.stdout+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self.stdout:
            line,self.stdout=self.stdout.split(b'\n',1)
            try: message=json.loads(line.decode('utf-8'))
            except (UnicodeDecodeError,json.JSONDecodeError): continue
            self._message(message)

    def _message(self,data):
        status=data.get('status')
        if status=='ready':
            expected=len(self.rows)
            if len(data.get('stems',[]))!=expected:
                self.state.setText('Le moteur a chargé un nombre inattendu de stems.')
                self.process.kill()
                return
            self.ready=True
            self.state.setText('⚡ LIVE · JUCE · '+str(expected)+' stems synchronisés')
            for item in self.controls: item.setEnabled(True)
            self.buttons.button(QDialogButtonBox.Save).setEnabled(True)
            self.poll.start()
            self._push_all()
        elif status=='error':
            self.state.setText('⚠ '+str(data.get('message','Erreur audio')))
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
        self.poll.stop()
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
