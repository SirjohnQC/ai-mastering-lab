"""Native Windows GUI for reference EQ candidate workflow (v0.6).

Starts existing command-line pipeline; it does NOT replace or patch the JUCE host.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QProcess, QUrl, Signal, QTimer, QObject
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QPlainTextEdit, QSplitter, QFrame, QMessageBox,
    QSlider, QProgressBar, QGroupBox, QGridLayout, QFileDialog, QDoubleSpinBox,
    QDockWidget, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QSpinBox, QLineEdit, QAbstractItemView, QDialog, QSplashScreen)
from .version import APP_VERSION, window_title
from .studio_brand import studio_icon
from .ollama_startup import ensure_ollama_running
from .live_ab import LiveAB
from .stem_plus_ui import StemPlusPage
from .auto_studio_ui import AutoStudioPage
from .plugin_setup_ui import PluginSetupDialog
from .plugin_registry import read_settings, selected_proq4
from .stem_inspector import default_stem_folder
from .gui_models import list_audio, find_report, audio_choices, audition_gain, store_preference
from .repair_markers import (ACTIONS, ISSUES, read_markers, write_markers, export_csv,
                             format_time, markers_path)

BG='#11151f'; PANEL='#1b2231'; INK='#e3e8f4'; MUTED='#9eabc0'; ACCENT='#8d91f5'


class EqPlot(QWidget):
    """Simple embedded EQ plan visualization. No external graph dependency."""
    def __init__(self):
        super().__init__(); self.setMinimumHeight(200)
        self.plans={}; self.selected='balanced'
    def set_data(self, report, profile):
        self.plans={key:report.get('candidate_profiles',{}).get(key,{}).get('eq_plan',[])
                    for key in ('warm','balanced','punchy')}
        self.selected=profile; self.update()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r=self.rect().adjusted(32,14,-20,-34)
        p.fillRect(self.rect(),QColor(PANEL))
        p.setPen(QPen(QColor('#394355'),1))
        for val in (-2,-1,0,1,2):
            y=r.center().y()-val*(r.height()/5)
            p.drawLine(r.left(),int(y),r.right(),int(y))
            p.setPen(QColor(MUTED));p.drawText(4,int(y)+4,f'{val:+}');p.setPen(QPen(QColor('#394355'),1))
        labels=['125','250','500','1k','2k','4k','8k']
        for i,label in enumerate(labels):
            x=r.left()+i*r.width()/6
            p.setPen(QColor(MUTED));p.drawText(int(x)-8,r.bottom()+18,label)
        shades={'balanced':'#5cd9b4','warm':'#f8b87a','punchy':'#a19dff'}
        for name,rows in self.plans.items():
            if len(rows)!=7:continue
            pen=QPen(QColor(shades[name]),3 if name==self.selected else 1.25)
            p.setPen(pen)
            pts=[]
            for i,row in enumerate(rows):
                val=max(-2.5,min(2.5,float(row.get('recommended_gain_db',0))))
                x=r.left()+i*r.width()/6;y=r.center().y()-val*(r.height()/5)
                pts.append((int(x),int(y)))
            for a,b in zip(pts,pts[1:]):p.drawLine(*a,*b)
            if name==self.selected:
                p.setBrush(QColor(shades[name]))
                for x,y in pts:p.drawEllipse(x-3,y-3,6,6)
        p.end()


class OllamaStartupBridge(QObject):
    status = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self,root:Path):
        super().__init__();self.root=root;self.report={};self.paths={};self.busy=False;self.last_position=0;self.ab=LiveAB();self.ab_signature=None
        self.setWindowTitle(window_title());self.resize(1140,760)
        self.setWindowIcon(studio_icon())
        self.setStyleSheet(f'''QWidget {{background:{BG};color:{INK};font-size:13px;}}
            QGroupBox,QFrame#panel {{background:{PANEL};border:1px solid #323a4d;border-radius:10px;margin-top:12px;padding:10px;}}
            QGroupBox::title {{subcontrol-origin:margin;left:12px;padding:0 5px;color:{ACCENT};}}
            QPushButton {{background:#353f60;border:0;border-radius:7px;padding:9px 13px;}}
            QPushButton:hover {{background:#4a5683;}}
            QPushButton:disabled {{background:#252b38;color:#77829a;}}
            QPushButton#primary {{background:#7779d9;color:white;font-weight:bold;}}
            QComboBox,QDoubleSpinBox {{background:#262f42;padding:7px;border:1px solid #46516c;border-radius:6px;}}
            QPlainTextEdit {{background:#121a26;border:1px solid #323a4d;border-radius:6px;}}
            QProgressBar {{background:#253044;border:0;border-radius:4px;}}
            QProgressBar::chunk {{background:{ACCENT};border-radius:4px;}}
            QTabWidget::pane {{border:0;border-top:1px solid #344158;}}
            QTabBar::tab {{background:#171e2c;color:#a8b6cb;padding:12px 18px;border-bottom:2px solid transparent;}}
            QTabBar::tab:selected {{color:#e9fff7;border-bottom:2px solid #73e2bf;}}
            QTabBar::tab:hover {{background:#253146;}}
            QPushButton:focus {{border:2px solid #aaa3ff;}}''')
        self.plugin_settings_path=self.root/'settings'/'vst_roles.json'
        ai_menu=self.menuBar().addMenu('Settings')
        ai_menu.addAction('Ollama & AI Models…').triggered.connect(self.open_ai_settings)
        ai_menu.addAction('Reconnect Ollama').triggered.connect(self.start_ollama_check)
        self._ollama_bridge = OllamaStartupBridge(self)
        self._ollama_bridge.status.connect(self._handle_ollama_status)
        self._ollama_check_running = False
        plugin_menu=self.menuBar().addMenu('Plugins')
        configure=plugin_menu.addAction('Configure installed VST3 plugins…')
        configure.triggered.connect(self.open_plugin_setup)
        self.workspace=QTabWidget();self.setCentralWidget(self.workspace)
        body=QWidget();self._mastering_page=body;self.workspace.addTab(body,'MASTERING  |  Stereo')
        main=QVBoxLayout(body);main.setSpacing(12)
        title=QLabel('◉  AI MASTERING LAB');title.setFont(QFont('Segoe UI',20,QFont.Bold));main.addWidget(title)
        subtitle=QLabel('Reference EQ  •  Local JUCE + FabFilter Pro-Q 4  •  EQ candidates, not final masters')
        subtitle.setStyleSheet(f'color:{MUTED}');main.addWidget(subtitle)
        files=QGroupBox('SONGS & REFERENCE');fg=QGridLayout(files)
        self.source=QComboBox();self.ref=QComboBox();self.source.setMinimumWidth(350)
        fg.addWidget(QLabel('Source'),0,0);fg.addWidget(self.source,0,1)
        fg.addWidget(QLabel('Reference'),1,0);fg.addWidget(self.ref,1,1)
        refresh=QPushButton('↻  Refresh folders');refresh.clicked.connect(self.refresh_files)
        folder=QPushButton('Open sound folder');folder.clicked.connect(self.open_sound)
        fg.addWidget(refresh,0,2);fg.addWidget(folder,1,2)
        main.addWidget(files)
        controls=QHBoxLayout();self.render=QPushButton('✦  GENERATE 3 CANDIDATES');self.render.setObjectName('primary')
        self.render.clicked.connect(self.start_render);controls.addWidget(self.render)
        self.preview=QPushButton('Preview EQ plans');self.preview.clicked.connect(lambda:self.start_render(False));controls.addWidget(self.preview)
        self.strength=QDoubleSpinBox();self.strength.setRange(.05,1);self.strength.setSingleStep(.05);self.strength.setValue(.55)
        controls.addWidget(QLabel('Strength'));controls.addWidget(self.strength)
        self.progress=QProgressBar();self.progress.setRange(0,1);self.progress.setValue(0);controls.addWidget(self.progress,1)
        main.addLayout(controls)
        split=QSplitter(Qt.Horizontal);main.addWidget(split,1)
        left=QWidget();ll=QVBoxLayout(left)
        self.plot=EqPlot();ll.addWidget(self.plot)
        picker=QHBoxLayout();self.profile=QComboBox();self.profile.addItems(['original','balanced','warm','punchy'])
        self.profile.currentTextChanged.connect(self.profile_changed)
        picker.addWidget(QLabel('Live A/B'));picker.addWidget(self.profile,1)
        self.choose=QPushButton('♥ Save my choice');self.choose.clicked.connect(self.save_choice)
        picker.addWidget(self.choose);ll.addLayout(picker)
        transport=QHBoxLayout();self.play=QPushButton('▶ Play');self.play.clicked.connect(self.toggle_play)
        self.stop=QPushButton('■ Stop');self.stop.clicked.connect(self.stop_play)
        transport.addWidget(self.play);transport.addWidget(self.stop)
        self.seek=QSlider(Qt.Horizontal);self.seek.setRange(0,1000);self.seek.sliderMoved.connect(self.seek_to)
        transport.addWidget(self.seek,1);ll.addLayout(transport)
        self.stats=QLabel('No candidate selected');self.stats.setWordWrap(True);self.stats.setStyleSheet(f'color:{MUTED}')
        ll.addWidget(self.stats);split.addWidget(left)
        right=QWidget();rl=QVBoxLayout(right)
        rl.addWidget(QLabel('Processing log'))
        self.log=QPlainTextEdit();self.log.setReadOnly(True);rl.addWidget(self.log,1)
        self.report_text=QPlainTextEdit();self.report_text.setReadOnly(True);self.report_text.setMaximumHeight(165)
        rl.addWidget(QLabel('Candidate QC'));rl.addWidget(self.report_text)
        split.addWidget(right);split.setSizes([700,420])
        self.statusBar().showMessage('Ready — source WAV preferred, reference WAV/MP3 accepted')
        self.process=QProcess(self);self.process.setWorkingDirectory(str(root))
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.render_finished)
        self.process.errorOccurred.connect(lambda _:self.log.appendPlainText('Process error: '+self.process.errorString()))
        self.timer=QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.update_transport)
        self.timer.start()
        self.seek.setEnabled(False)
        self.create_repair_dock()
        self.create_stem_dock()
        self.stem_plus=StemPlusPage(self.root)
        self.stem_plus.guided_frontend=True
        self.stem_plus.advanced_toggle.setChecked(True)
        self.stem_plus.sourceExported.connect(lambda _path: self.refresh_files())
        self.workspace.insertTab(0, self.stem_plus, 'Advanced  |  STEM+ Console')
        self.auto_studio=AutoStudioPage(self.root, self.stem_plus)
        self.auto_studio.openAdvanced.connect(lambda: self.workspace.setCurrentWidget(self.stem_plus))
        self.auto_studio.openMastering.connect(self.accept_auto_studio_mix)
        self.workspace.insertTab(0, self.auto_studio, 'AUTO STUDIO')
        self.workspace.setCurrentWidget(self.auto_studio)
        self.workspace.setTabToolTip(self.workspace.indexOf(self.auto_studio),
            'Start here: import, produce, compare and master a song, or open Album Mode.')
        self.workspace.setTabToolTip(self.workspace.indexOf(self.stem_plus),
            'Advanced stem mixing: gain, pan, solo, mute and individual effects.')
        self.workspace.setTabToolTip(self.workspace.indexOf(body),
            'Advanced stereo reference EQ candidates. Final mastering is in Auto Studio.')
        self.workspace.currentChanged.connect(self.workspace_changed)
        self.source.currentIndexChanged.connect(self.reload_source)
        
        self.ref.currentIndexChanged.connect(self.load_report)
        self.refresh_files()
        self.refresh_mastering_actions()
        self.workspace_changed(self.workspace.currentIndex())

    def start_ollama_check(self):
        """Verify/start local Ollama outside Qt's GUI thread (at most one attempt)."""
        import threading
        if self._ollama_check_running:
            self.statusBar().showMessage('Ollama : vérification déjà en cours…', 6000)
            return
        self._ollama_check_running = True
        self.statusBar().showMessage('Ollama : vérification du serveur local…')

        def run():
            try:
                result = ensure_ollama_running()
                self._ollama_bridge.status.emit(result.message)
            except Exception as exc:
                self._ollama_bridge.status.emit(f'Ollama non disponible : {exc} (mixage local toujours disponible)')
            finally:
                # Do not update Qt widgets from worker thread.
                self._ollama_bridge.status.emit('__ollama_check_finished__')

        threading.Thread(target=run, daemon=True, name='OllamaStartup').start()

    def _handle_ollama_status(self, message):
        if message == '__ollama_check_finished__':
            self._ollama_check_running = False
        else:
            self.statusBar().showMessage(message, 15000)

    def open_ai_settings(self):
        from .ai_settings_ui import AISettingsDialog
        AISettingsDialog(self.root, self).exec()

    def open_plugin_setup(self):
        dialog=PluginSetupDialog(self.plugin_settings_path,self)
        if dialog.exec()==QDialog.Accepted:
            self.statusBar().showMessage('VST preferences saved. New renders use the selected compatible EQ plugin.')

    def accept_auto_studio_mix(self, path):
        """Send the selected premix to existing mastering source input."""
        self.refresh_files()
        for i in range(self.source.count()):
            if self.source.itemData(i)==str(path):
                self.source.setCurrentIndex(i)
                break
        self.workspace.setCurrentIndex(self.workspace.indexOf(self._mastering_page))
        self.statusBar().showMessage('Prémix sélectionné pour mastering : '+Path(path).name+' — référence requise.', 15000)

    def workspace_changed(self,index):
        # Keep older inspector/repair docks with the stereo page only.
        visible=(self.workspace.tabText(index).startswith('MASTERING'))
        self.repair_dock.setVisible(visible)
        self.stem_dock.setVisible(visible)
        if not visible:
            self.statusBar().showMessage('FRANKENSTEM · ' + self.workspace.tabText(index))

    def create_repair_dock(self):
        """Human annotations; no untrained AI detection claims."""
        self.repair_dock=QDockWidget('REPAIR TIMELINE — manual markers',self)
        self.repair_dock.setObjectName('repairTimeline')
        self.repair_dock.setAllowedAreas(Qt.BottomDockWidgetArea|Qt.RightDockWidgetArea)
        holder=QWidget();layout=QVBoxLayout(holder)
        info=QLabel('Mark an exact passage, choose a repair plan, and optionally link a new voice/guitar take. No audio is modified.')
        info.setWordWrap(True);info.setStyleSheet(f'color:{MUTED}')
        layout.addWidget(info)
        self.repair_table=QTableWidget(0,5)
        self.repair_table.setHorizontalHeaderLabels(['Start','End','Issue','Plan','Notes'])
        self.repair_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.repair_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.repair_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.repair_table.itemSelectionChanged.connect(self.marker_selected)
        self.repair_table.setMinimumHeight(125)
        layout.addWidget(self.repair_table)
        controls=QHBoxLayout()
        self.marker_start=QSpinBox();self.marker_end=QSpinBox()
        for spin in (self.marker_start,self.marker_end):
            spin.setRange(0,7200000);spin.setSuffix(' ms');spin.setSingleStep(100)
        self.marker_end.setValue(5000)
        here=QPushButton('Set start = playhead');here.clicked.connect(self.marker_from_playhead)
        controls.addWidget(here)
        controls.addWidget(QLabel('Start'));controls.addWidget(self.marker_start)
        controls.addWidget(QLabel('End'));controls.addWidget(self.marker_end)
        layout.addLayout(controls)
        fields=QHBoxLayout()
        self.issue=QComboBox();self.issue.addItems(list(ISSUES))
        self.repair_action=QComboBox();self.repair_action.addItems(list(ACTIONS))
        self.marker_notes=QLineEdit();self.marker_notes.setPlaceholderText('Why this passage needs attention')
        fields.addWidget(QLabel('Issue'));fields.addWidget(self.issue)
        fields.addWidget(QLabel('Action'));fields.addWidget(self.repair_action)
        fields.addWidget(self.marker_notes,1)
        layout.addLayout(fields)
        buttons=QHBoxLayout()
        for title, callback in [('Add marker',self.add_marker),('Delete selected',self.delete_marker),
                                ('Play selected range',self.play_marker),('Attach voice/guitar WAV',self.attach_take),
                                ('Export CSV for Cubase',self.export_markers)]:
            b=QPushButton(title);b.clicked.connect(callback);buttons.addWidget(b)
        layout.addLayout(buttons)
        self.marker_file_label=QLabel('Markers are stored separately from your audio files.')
        self.marker_file_label.setStyleSheet(f'color:{MUTED}')
        layout.addWidget(self.marker_file_label)
        self.repair_dock.setWidget(holder)
        self.addDockWidget(Qt.BottomDockWidgetArea,self.repair_dock)
        self.marker_items=[]

    def create_stem_dock(self):
        self.stem_dock=QDockWidget('STEM INSPECTOR — review suggestions', self)
        self.stem_dock.setObjectName('stemInspector')
        self.stem_dock.setAllowedAreas(Qt.BottomDockWidgetArea|Qt.RightDockWidgetArea)
        holder=QWidget(); layout=QVBoxLayout(holder)
        intro=QLabel('Read-only checks, NOT an AI detector. Flags may be intentional musical choices. Inspect with your ears.')
        intro.setWordWrap(True);intro.setStyleSheet(f'color:{MUTED}');layout.addWidget(intro)
        choose=QHBoxLayout()
        self.stem_dir=QLineEdit(str(default_stem_folder(self.root,None)))
        self.stem_dir.setPlaceholderText('Folder containing vocals, drums, guitars, bass stems')
        browse=QPushButton('Browse');browse.clicked.connect(self.browse_stems)
        self.scan_stems_button=QPushButton('Scan stems');self.scan_stems_button.setObjectName('primary')
        self.scan_stems_button.clicked.connect(self.start_stem_scan)
        choose.addWidget(self.stem_dir,1);choose.addWidget(browse);choose.addWidget(self.scan_stems_button)
        layout.addLayout(choose)
        self.stem_table=QTableWidget(0,6)
        self.stem_table.setHorizontalHeaderLabels(['Stem','Start','End','Flag','Priority','Reason'])
        self.stem_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.stem_table.horizontalHeader().setStretchLastSection(True)
        self.stem_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.stem_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.stem_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stem_table.setMinimumHeight(145)
        self.stem_table.itemSelectionChanged.connect(self.stem_row_selected)
        layout.addWidget(self.stem_table)
        row=QHBoxLayout()
        self.stem_result=QLabel('Choose a stem folder and click Scan stems.')
        self.stem_result.setWordWrap(True);self.stem_result.setStyleSheet(f'color:{MUTED}')
        make=QPushButton('Add selected as repair marker');make.clicked.connect(self.stem_to_marker)
        row.addWidget(self.stem_result,1);row.addWidget(make)
        layout.addLayout(row)
        mixrow=QHBoxLayout()
        self.mix_config_btn=QPushButton('Create stem mix config')
        self.mix_config_btn.clicked.connect(self.create_stem_mix_config)
        self.mix_render_btn=QPushButton('Render stem mix preview')
        self.mix_render_btn.clicked.connect(self.start_stem_mix)
        mixrow.addWidget(self.mix_config_btn);mixrow.addWidget(self.mix_render_btn)
        layout.addLayout(mixrow)
        self.mix_status=QLabel('Edit stem-mix.json to set gain, pan, mute and optional Pro-Q 4 EQ per stem.')
        self.mix_status.setWordWrap(True);layout.addWidget(self.mix_status)
        self.mix_process=QProcess(self)
        self.mix_process.setWorkingDirectory(str(self.root))
        self.mix_process.setProcessChannelMode(QProcess.MergedChannels)
        self.mix_process.finished.connect(self.stem_mix_finished)
        self.mix_process.errorOccurred.connect(lambda _: self.mix_status.setText('Mix process error: '+self.mix_process.errorString()))
        self.stem_dock.setWidget(holder)
        self.addDockWidget(Qt.BottomDockWidgetArea,self.stem_dock)
        self.tabifyDockWidget(self.repair_dock,self.stem_dock)
        self.stem_dock.raise_()
        self.stem_rows=[];self.stem_report={}
        self.stem_process=QProcess(self)
        self.stem_process.setWorkingDirectory(str(self.root))
        self.stem_process.setProcessChannelMode(QProcess.MergedChannels)
        self.stem_process.finished.connect(self.stem_scan_finished)
        self.stem_process.errorOccurred.connect(lambda _: self.stem_result.setText('Scanner error: '+self.stem_process.errorString()))

    def create_stem_mix_config(self):
        folder=Path(self.stem_dir.text().strip())
        if not folder.is_dir():
            QMessageBox.warning(self,'Folder missing','Choose a valid stem folder first.');return
        script=self.root/'scripts'/'stem_mix.py'
        if not script.is_file():
            QMessageBox.warning(self,'Mixer missing',f'Missing: {script}');return
        if self.mix_process.state()!=QProcess.NotRunning:return
        self.mix_config_btn.setEnabled(False);self.mix_render_btn.setEnabled(False)
        self.mix_status.setText('Creating stem-mix.json (no audio changes).')
        self.mix_process.start(sys.executable,['-u',str(script),'--folder',str(folder),'--make-config'])

    def start_stem_mix(self):
        folder=Path(self.stem_dir.text().strip())
        if not folder.is_dir():
            QMessageBox.warning(self,'Folder missing','Choose a valid stem folder first.');return
        config=folder/'stem-mix.json'
        if not config.is_file():
            QMessageBox.information(self,'Config required','Click Create stem mix config first, then edit the JSON file to select processing.');return
        if self.mix_process.state()!=QProcess.NotRunning:return
        script=self.root/'scripts'/'stem_mix.py'
        self.mix_config_btn.setEnabled(False);self.mix_render_btn.setEnabled(False)
        self.mix_status.setText('Rendering stem mix preview… source files remain untouched.')
        self.mix_process.start(sys.executable,['-u',str(script),'--folder',str(folder)])

    def stem_mix_finished(self, code, _status):
        self.mix_config_btn.setEnabled(True);self.mix_render_btn.setEnabled(True)
        raw=bytes(self.mix_process.readAllStandardOutput()).decode('utf-8',errors='replace').strip()
        self.log.appendPlainText('STEM MIX: '+raw[-1800:])
        try:
            result=json.loads(raw.splitlines()[-1])
            if code or result.get('status')!='ok':
                raise ValueError(result.get('error',raw[-300:]))
            if result.get('config'):
                self.mix_status.setText('Created '+result['config']+'. Edit the JSON before rendering.')
            else:
                self.mix_status.setText('Mix preview saved: '+result['output']+' (not mastered)')
        except (ValueError,IndexError) as exc:
            self.mix_status.setText('Mix operation failed: '+str(exc))

    def browse_stems(self):
        folder=QFileDialog.getExistingDirectory(self,'Choose stems directory',self.stem_dir.text())
        if folder:self.stem_dir.setText(folder)

    def start_stem_scan(self):
        if self.stem_process.state()!=QProcess.NotRunning:
            return
        folder=Path(self.stem_dir.text().strip())
        if not folder.is_dir():
            QMessageBox.warning(self,'Stem folder missing',f'Directory does not exist: {folder}')
            return
        script=self.root/'scripts'/'stem_inspector.py'
        if not script.is_file():
            QMessageBox.warning(self,'Scanner missing',f'Missing script: {script}')
            return
        args=['-u',str(script),'--folder',str(folder),'--root',str(self.root)]
        if self.current_source():args.extend(['--source',str(self.current_source())])
        self.scan_stems_button.setEnabled(False)
        self.stem_result.setText('Scanning stems… original files will not be changed.')
        self.stem_process.start(sys.executable,args)

    def stem_scan_finished(self, code, _status):
        self.scan_stems_button.setEnabled(True)
        raw=bytes(self.stem_process.readAllStandardOutput()).decode('utf-8',errors='replace').strip()
        try:
            result=json.loads(raw.splitlines()[-1])
            if code!=0 or result.get('status')!='ok':
                raise ValueError(result.get('error') or raw[-800:])
            report=json.loads(Path(result['report_path']).read_text(encoding='utf-8'))
            self.stem_report=report
            self.stem_rows=[]
            self.stem_table.setRowCount(0)
            for stem in report.get('stems',[]):
                for flag in stem.get('suspicions',[]):
                    item={'stem':Path(stem['file']).name,**flag}
                    self.stem_rows.append(item)
                    r=self.stem_table.rowCount();self.stem_table.insertRow(r)
                    vals=[item['stem'],format_time(item['start_ms']),format_time(item['end_ms']),
                          item['issue'],item['severity'],item['reason']]
                    for col,val in enumerate(vals):
                        self.stem_table.setItem(r,col,QTableWidgetItem(str(val)))
            self.stem_result.setText(f"{len(report.get('stems',[]))} stem(s), {len(self.stem_rows)} suggested review range(s), {len(report.get('errors',[]))} file error(s). Report: {result['report_path']}")
            for error in report.get('errors',[]):
                self.log.appendPlainText('STEM ERROR: '+error['file']+' — '+error['error'])
        except (ValueError,OSError,KeyError,IndexError) as exc:
            self.stem_result.setText('Scan failed: '+str(exc))
            self.log.appendPlainText('Stem scan output: '+raw[-1000:])

    def selected_stem_flag(self):
        selected=self.stem_table.selectionModel().selectedRows()
        i=selected[0].row() if selected else -1
        return self.stem_rows[i] if 0<=i<len(self.stem_rows) else None

    def stem_row_selected(self):
        flag=self.selected_stem_flag()
        if not flag:return
        self.marker_start.setValue(flag['start_ms'])
        self.marker_end.setValue(flag['end_ms'])
        self.marker_notes.setText(f"{flag['stem']}: {flag['reason']} (automatic heuristic; confirm by ear)")
        self.repair_action.setCurrentText('review')
        mapper={'possible_clipping':'digital_artifact','invalid_samples':'digital_artifact',
                'possible_dropout':'other','high_frequency_energy':'sibilance'}
        self.issue.setCurrentText(mapper.get(flag['issue'],'other'))

    def stem_to_marker(self):
        flag=self.selected_stem_flag()
        if not flag:
            QMessageBox.information(self,'No selection','Select a flagged range first.');return
        if not self.current_source():
            QMessageBox.information(self,'No song selected','Choose a source song before creating repair markers.');return
        self.stem_row_selected()
        marker=dict(start_ms=flag['start_ms'],end_ms=flag['end_ms'],
                    issue=self.issue.currentText(),action='review',
                    notes=self.marker_notes.text(),take_path='')
        if self.save_marker_items([*self.marker_items,marker]):
            self.statusBar().showMessage('Review marker added. No stem or source audio was modified.')

    def current_source(self):
        value=self.source.currentData()
        return Path(value) if value else None

    def reload_source(self):
        self.invalidate_ab()
        self.load_report()
        self.load_repair_markers()
        self.refresh_mastering_actions()
        if hasattr(self, "stem_dir") and self.current_source():
            self.stem_dir.setText(str(default_stem_folder(self.root, self.current_source())))

    def update_repair_duration(self, duration):
        if duration>0:
            for widget in (self.marker_start,self.marker_end):widget.setMaximum(duration)

    def load_repair_markers(self):
        self.marker_items=[];self.repair_table.setRowCount(0)
        source=self.current_source()
        if not source:return
        try:self.marker_items=read_markers(self.root,source)
        except (OSError,ValueError) as exc:
            self.statusBar().showMessage('Repair markers could not be loaded: '+str(exc))
            return
        for i,m in enumerate(self.marker_items):
            self.repair_table.insertRow(i)
            for col,value in enumerate([format_time(m['start_ms']),format_time(m['end_ms']),
                                        m['issue'],m['action'],m.get('notes','')]):
                self.repair_table.setItem(i,col,QTableWidgetItem(str(value)))
        self.marker_file_label.setText(f'{len(self.marker_items)} marker(s) · {markers_path(self.root,source)}')

    def marker_from_playhead(self):
        pos=max(0,self.ab.position_ms)
        self.marker_start.setValue(pos)
        self.marker_end.setValue(min(self.marker_end.maximum(),pos+5000))

    def selected_marker_index(self):
        rows=self.repair_table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def marker_selected(self):
        i=self.selected_marker_index()
        if i is None or i>=len(self.marker_items):return
        m=self.marker_items[i]
        self.marker_start.setValue(m['start_ms']);self.marker_end.setValue(m['end_ms'])
        self.issue.setCurrentText(m['issue']);self.repair_action.setCurrentText(m['action'])
        self.marker_notes.setText(m.get('notes',''))

    def save_marker_items(self, items):
        source=self.current_source()
        if not source:
            QMessageBox.warning(self,'No source','Select a source song first.');return False
        try:
            write_markers(self.root,source,items,self.ab.duration_ms or None)
        except (ValueError,OSError) as exc:
            QMessageBox.warning(self,'Invalid marker',str(exc));return False
        self.load_repair_markers()
        return True

    def add_marker(self):
        source=self.current_source()
        if not source:return
        marker=dict(start_ms=self.marker_start.value(),end_ms=self.marker_end.value(),
                    issue=self.issue.currentText(),action=self.repair_action.currentText(),
                    notes=self.marker_notes.text(),take_path='')
        self.save_marker_items([*self.marker_items,marker])

    def delete_marker(self):
        i=self.selected_marker_index()
        if i is None:return
        self.save_marker_items([m for j,m in enumerate(self.marker_items) if j!=i])

    def play_marker(self):
        i=self.selected_marker_index()
        if i is None:return
        m=self.marker_items[i]
        source=self.current_source()
        if source is None:return
        if not self.ensure_ab_loaded():return
        if 'original' not in self.ab.tracks:return
        self.ab.pause()
        self.ab.choose('original')
        self.profile.setCurrentText('original')
        self.ab.seek(m['start_ms']);self.ab.set_range_end(m['end_ms'])
        self.last_position=m['start_ms'];self.ab.play()

    def attach_take(self):
        i=self.selected_marker_index()
        if i is None:
            QMessageBox.information(self,'Select marker','Select a marker before attaching a recording.');return
        path,_=QFileDialog.getOpenFileName(self,'Attach a replacement recording',str(self.root/'sound'),
                                           'WAV audio (*.wav);;All files (*)')
        if not path:return
        # Record the original location; do not resample, replace or silently overdub audio.
        items=[dict(m) for m in self.marker_items];items[i]['take_path']=str(Path(path).resolve())
        if self.save_marker_items(items):self.statusBar().showMessage('Take linked; no audio was modified.')

    def export_markers(self):
        source=self.current_source()
        if source is None:return
        try:path=export_csv(self.root,source)
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'Export failed',str(exc));return
        self.statusBar().showMessage(f'Markers CSV exported: {path}')

    def open_sound(self):
        path=self.root/'sound';path.mkdir(parents=True,exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def refresh_files(self):
        old_source=self.source.currentData();old_ref=self.ref.currentData()
        self.source.clear();self.ref.clear()
        for p in list_audio(self.root/'sound'/'source'):self.source.addItem(p.name,str(p))
        for p in list_audio(self.root/'sound'/'ref'):self.ref.addItem(p.name,str(p))
        for combo,old in ((self.source,old_source),(self.ref,old_ref)):
            if old is not None:
                for i in range(combo.count()):
                    if combo.itemData(i)==old:combo.setCurrentIndex(i);break
        self.invalidate_ab()
        self.load_report()
        self.load_repair_markers()
        self.refresh_mastering_actions()

    def refresh_mastering_actions(self):
        has_source=self.current_source() is not None
        has_reference=self.ref.currentData() is not None
        ready=has_source and has_reference and not self.busy
        self.render.setEnabled(ready)
        self.preview.setEnabled(ready)
        self.play.setEnabled(has_source and not self.busy)
        self.stop.setEnabled(has_source and not self.busy)
        self.choose.setEnabled(bool(self.report) and has_source)
        self.profile.setEnabled(has_source)
        if not has_source or not has_reference:
            self.statusBar().showMessage('Charge une source et une référence pour activer le mastering.')

    def get_selections(self):
        if self.source.currentData() is None or self.ref.currentData() is None:
            raise ValueError('Add audio to sound/source and sound/ref, then refresh.')
        return Path(self.source.currentData()),Path(self.ref.currentData())

    def start_render(self, render=True):
        if self.busy:return
        try:
            source,ref=self.get_selections()
        except ValueError as exc:
            QMessageBox.warning(self,'Missing audio',str(exc));return
        script=self.root/'scripts'/'master_candidates.py'
        if not script.exists():
            QMessageBox.critical(self,'Missing script',f'Not found: {script}');return
        self.stop_play();self.busy=True;self.render.setEnabled(False);self.preview.setEnabled(False)
        self.refresh_mastering_actions()
        self.progress.setRange(0,0);self.log.clear();self.log.appendPlainText(f'Source: {source}\nReference: {ref}')
        args=['-u',str(script),'--source',str(source),'--reference',str(ref),
              '--strength',str(self.strength.value())]
        if render:
            chosen=selected_proq4(self.plugin_settings_path)
            if chosen is not None:args.extend(['--plugin',str(chosen)])
            else:
                QMessageBox.warning(self,'Pro-Q 4 not configured','Automatic EQ rendering currently supports Pro-Q 4 only. Open Plugins → Configure installed VST3 plugins and choose Pro-Q 4 for Corrective EQ.');self.busy=False;self.render.setEnabled(True);self.preview.setEnabled(True);self.progress.setRange(0,1);self.refresh_mastering_actions();return
            args.append('--render')
        self.process.start(sys.executable,args)

    def read_stdout(self):
        self.log.appendPlainText(bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace').rstrip())
    def read_stderr(self):
        self.log.appendPlainText(bytes(self.process.readAllStandardError()).decode('utf-8',errors='replace').rstrip())
    def render_finished(self,exit_code,status):
        self.busy=False;self.refresh_mastering_actions()
        self.progress.setRange(0,1);self.progress.setValue(1 if exit_code==0 else 0)
        self.log.appendPlainText(f'Completed with exit code {exit_code}')
        self.invalidate_ab()
        self.load_report()
        if exit_code!=0:QMessageBox.warning(self,'Render failed','See processing log for details.')
        else:self.statusBar().showMessage('Candidate report updated. Select and audition tracks.')

    def load_report(self):
        self.report={};self.paths={};self.report_text.clear();self.plot.set_data({},'balanced')
        try:source,ref=self.get_selections()
        except ValueError:return
        path=find_report(self.root,source)
        if not path:return
        try:
            report=json.loads(path.read_text(encoding='utf-8'))
            if Path(report.get('reference','')).resolve()!=ref.resolve():
                self.report_text.setPlainText('Existing report uses a different reference. Render again.');return
            self.report=report;self.paths=audio_choices(report,source)
            self.profile_changed(self.profile.currentText())
        except (OSError,ValueError,TypeError) as exc:
            self.report_text.setPlainText('Invalid report: '+str(exc))
        finally:
            self.refresh_mastering_actions()

    def invalidate_ab(self):
        self.ab.close()
        self.ab_signature=None
        self.seek.setEnabled(False)
        self.play.setText('▶ Play')

    def ensure_ab_loaded(self):
        """Load all available renders at once to avoid Qt media source restarts."""
        if not self.paths:
            source=self.current_source()
            if source:self.paths={'original':source}
        paths={name:path for name,path in self.paths.items() if Path(path).is_file()}
        if not paths:
            QMessageBox.information(self,'No audio','Choose a source and render candidates first.');return False
        signature=tuple(sorted((k,str(v),v.stat().st_size,v.stat().st_mtime_ns) for k,v in paths.items()))
        if signature != self.ab_signature:
            try:
                gains={name:0.75*audition_gain(self.report,name) for name in paths}
                self.ab.load(paths,gains)
            except Exception as exc:
                QMessageBox.warning(self,'Audio loading failed',str(exc));return False
            self.ab_signature=signature
            self.seek.setEnabled(True)
            self.update_repair_duration(self.ab.duration_ms)
        return True

    def profile_changed(self,name):
        # IMPORTANT: switching profile NEVER stops the shared audio engine.
        self.plot.set_data(self.report,name)
        if self.ab_signature:
            if name in self.ab.tracks:
                self.ab.choose(name)
            else:
                self.statusBar().showMessage(f'{name} is not rendered yet.')
        if not self.report:return
        if name=='original':
            obj=self.report.get('original',{})
            self.stats.setText(f"ORIGINAL · RMS {obj.get('rms_dbfs','—')} dBFS · sample peak {obj.get('peak_dbfs','—')} dBFS")
            self.report_text.setPlainText('Unprocessed source (baseline).')
            return
        entry=self.report.get('candidate_profiles',{}).get(name,{})
        metrics=entry.get('metrics',{});a=metrics.get('analysis',{})
        self.stats.setText(f"{name.upper()} · {entry.get('status','not rendered')} · RMS {a.get('rms_dbfs','—')} dBFS · sample peak {a.get('peak_dbfs','—')} dBFS")
        lines=[f"Spectral distance Δ: {metrics.get('spectral_distance_change_db','—')} dB",
               'Spectral distance is NOT a listening-quality score.','Sample peak/RMS are not true peak/LUFS.']
        lines.extend('WARNING: '+w for w in metrics.get('warnings',[]))
        self.report_text.setPlainText('\n'.join(lines))

    def toggle_play(self):
        if self.current_source() is None:
            QMessageBox.information(self,'Aucun fichier audio','Charge une chanson dans sound/source avant de démarrer la lecture.');return
        if not self.ensure_ab_loaded():return
        name=self.profile.currentText()
        if name not in self.ab.tracks:
            QMessageBox.information(self,'Not rendered',f'{name} has no audio file. Render candidates first.');return
        self.ab.choose(name)
        if self.ab.playing:
            self.ab.pause()
        else:
            try:self.ab.play()
            except Exception as exc:
                QMessageBox.warning(self,'Playback failed',str(exc))

    def stop_play(self):
        self.ab.stop()
        self.play.setText('▶ Play')
        self.seek.setValue(0)

    def update_transport(self):
        duration=self.ab.duration_ms
        pos=self.ab.position_ms
        if duration>0 and not self.seek.isSliderDown():
            self.seek.setValue(int(1000*pos/duration))
        self.last_position=pos
        self.play.setText('❚❚ Pause' if self.ab.playing else '▶ Play')

    def seek_to(self,value):
        if self.ab.duration_ms>0:
            self.ab.seek(int(self.ab.duration_ms*value/1000))
            self.last_position=self.ab.position_ms

    def closeEvent(self,event):
        self.auto_studio.shutdown()
        self.stem_plus.shutdown()
        self.ab.close()
        super().closeEvent(event)

    def save_choice(self):
        try:source,ref=self.get_selections()
        except ValueError as e:QMessageBox.warning(self,'No files',str(e));return
        name=self.profile.currentText()
        if name not in self.paths:
            QMessageBox.information(self,'No candidate','Render and listen to a candidate before selecting it.');return
        target=self.root/'sound'/'output'/'preferences.json'
        try:store_preference(target,source,ref,name)
        except OSError as e:QMessageBox.critical(self,'Save failed',str(e));return
        self.statusBar().showMessage(f'Preference saved: {name} → {target}')


def main(root:Path|None=None)->int:
    root=root or Path(__file__).resolve().parents[2]
    app=QApplication(sys.argv)
    app.setWindowIcon(studio_icon())
    root=Path(root)
    # First-run setup is optional; Cancel leaves existing operation available.
    try:
        if not read_settings(root/'settings'/'vst_roles.json').get('setup_complete'):
            PluginSetupDialog(root/'settings'/'vst_roles.json').exec()
    except (ValueError,OSError) as exc:
        QMessageBox.warning(None,'Plugin settings',f'Plugin setup could not load: {exc}')
    # Run the JUCE device preflight in the startup splash, not on opening
    # a song. This process has a hard timeout and never exports audio.
    splash_art=QPixmap(570,190)
    splash_art.fill(QColor('#171923'))
    splash=QSplashScreen(splash_art)
    splash.show()
    splash.showMessage('FRANKENSTEM · Vérification du moteur audio JUCE…',
                       Qt.AlignCenter|Qt.AlignBottom,QColor('#e7e0ff'))
    app.processEvents()
    from .live_engine_startup import check_engine
    live_preflight=check_engine(root,timeout=5)
    splash.showMessage('FRANKENSTEM · Chargement de l’interface…',
                       Qt.AlignCenter|Qt.AlignBottom,QColor('#e7e0ff'))
    app.processEvents()
    win=MainWindow(root);win.show()
    splash.finish(win)
    # Permanent status: the Ollama startup check uses showMessage() and would
    # otherwise immediately overwrite the JUCE preflight diagnostic.
    win.live_engine_status=QLabel(
        ('⚡ Live Engine · ' if live_preflight['ready'] else
         '⚠ Live Engine · ')+live_preflight['reason'])
    win.live_engine_status.setToolTip(live_preflight['reason'])
    win.live_engine_status.setStyleSheet(
        'color:#7ee3ad;' if live_preflight['ready'] else 'color:#ffcb7d;')
    win.statusBar().addPermanentWidget(win.live_engine_status,1)
    QTimer.singleShot(0, win.start_ollama_check)
    return app.exec()
