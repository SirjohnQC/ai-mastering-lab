"""Album Studio — WAV batch mastering and evaluated stem mix candidates."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QComboBox, QFileDialog, QMessageBox, QProgressBar, QScrollArea,
    QListWidget, QListWidgetItem, QAbstractItemView, QApplication, QDialog, QSlider,
    QCheckBox, QDoubleSpinBox, QDialogButtonBox, QPlainTextEdit, QMenu)

from .album_project import (empty_project, load_project, save_project,
                            add_entries, discover_album, album_summary, reorder_tracks, move_track_onto)
from .album_match_advisor import advise_album, localized_card
from .ui_language import get_language
from .version import APP_VERSION
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class AlbumReleaseCheckWorker(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object, str)

    def __init__(self, tracks, target, parent=None):
        super().__init__(parent)
        self.tracks = tracks
        self.target = target
        self.stop = threading.Event()

    def run(self):
        from .album_release_check import check_album_release

        try:
            report = check_album_release(self.tracks, self.target, stop=self.stop,
                                         progress=self.progress.emit)
            self.completed.emit(report, '')
        except Exception as exc:
            self.completed.emit(None, str(exc))


class AlbumBatchWorker(QThread):
    item = Signal(int, str, object, str)  # index, status, QC result, error
    stage = Signal(int, int, str)          # number finished, total, message
    done = Signal(bool)                   # cancelled

    def __init__(self, entries, target, parent=None, *, reference_path=None, external_reference_wav=None, eq_root=None, eq_plugin=None):
        super().__init__(parent)
        self.eq_root = eq_root
        self.eq_plugin = eq_plugin
        self.entries = entries
        self.target = Path(target)
        self.reference_path = reference_path
        self.external_reference_wav = external_reference_wav
        self.stop_event = threading.Event()

    def cancel(self):
        self.stop_event.set()

    def run(self):
        from .auto_master import master_song, MasteringCancelled
        from .album_stem_pipeline import source_signature, can_reuse_master, master_stem_folder
        from .album_export_naming import rename_album_master
        from .album_stem_pipeline import master_album_with_eq
        master = master_song
        if self.eq_plugin is not None:
            def master(source, target, *, stop):
                return master_album_with_eq(source, target, root=self.eq_root,
                    plugin=self.eq_plugin, reference_path=self.reference_path, stop=stop,
                    progress=lambda message: self.stage.emit(finished, count, message))
        count = len(self.entries)
        finished = 0
        for idx, row in self.entries:
            if self.stop_event.is_set():
                break
            if can_reuse_master(row, external_reference_wav=self.external_reference_wav,
                                corrective_eq=self.eq_plugin is not None):
                self.item.emit(idx, 'qc_pass', row.get('result'), '')
            elif (row['kind'] == 'stems' and not Path(row['path']).is_dir()) or (row['kind'] == 'stereo' and not Path(row['path']).is_file()):
                self.item.emit(idx, 'error', None, 'Source audio introuvable')
            else:
                try:
                    if row['kind'] == 'stems':
                        result = master_stem_folder(row['path'], self.target, stop=self.stop_event,
                            progress=lambda message, completed=finished: self.stage.emit(completed, count, message),
                            reference_path=self.reference_path,
                            external_reference_wav=self.external_reference_wav,
                            stem_saturation=row.get('stem_saturation'),
                            de_sizzle=row.get('stem_de_sizzle'), master_fn=master)
                    else:
                        self.stage.emit(finished, count, 'Mastering : ' + row['title'])
                        result = rename_album_master(dict(master(row['path'], self.target, stop=self.stop_event)), row['title'])
                        result['album_source_signature'] = source_signature(row['path'], 'stereo')
                    self.item.emit(idx, result['status'], result, '')
                except MasteringCancelled:
                    self.stop_event.set()
                    break
                except Exception as exc:
                    self.item.emit(idx, 'error', None, str(exc))
            finished += 1
            self.stage.emit(finished, count, f'{finished}/{count} chansons examinées')
        self.done.emit(self.stop_event.is_set())

class MasterRecognitionWorker(QThread):
    item = Signal(str, object, str)
    finished_scan = Signal(int, int)

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths=tuple(paths)

    def run(self):
        from .existing_master_import import recognize_master, ExistingMasterError
        from .album_stem_pipeline import source_signature
        success=0
        for path in self.paths:
            try:
                result=recognize_master(path)
                result['album_source_signature']=source_signature(path,'stereo')
                result['album_imported_existing_master']=True
                self.item.emit(path,result,'')
                success+=1
            except (ExistingMasterError,OSError,ValueError) as exc:
                self.item.emit(path,None,str(exc))
        self.finished_scan.emit(success,len(self.paths))


class AlbumIntelligenceWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, project, reference_index, parent=None, *, external_reference_wav=None):
        super().__init__(parent)
        self.project_snapshot = json.loads(json.dumps(project))
        self.reference_index = reference_index
        self.external_reference_wav = external_reference_wav

    def run(self):
        from .album_intelligence import compare_album
        try:
            self.completed.emit(compare_album(
                self.project_snapshot, reference_index=self.reference_index,
                external_reference_wav=self.external_reference_wav))
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class AlbumOrderList(QListWidget):
    """Drop on a *whole song card*, never on a tiny insertion indicator."""

    orderRequested = Signal(str, str)  # dragged source path, hovered target path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_source_path = None
        self._hovered_item = None
        self.setDropIndicatorShown(False)

    def _highlight_target(self, item):
        if self._hovered_item is item:
            return
        normal = ('QFrame {background:#1b1d29;border:1px solid #3a3d50;'
                  'border-radius:9px} QLabel {background:transparent;border:none}')
        active = ('QFrame {background:#292943;border:2px solid #a99bff;'
                  'border-radius:9px} QLabel {background:transparent;border:none}')
        old = self.itemWidget(self._hovered_item) if self._hovered_item is not None else None
        if old is not None:
            old.setStyleSheet(normal)
        self._hovered_item = item
        card = self.itemWidget(item) if item is not None else None
        if card is not None:
            card.setStyleSheet(active)

    def dragEnterEvent(self, event):
        if (event.source() is self and self._drag_source_path
                and self.dragDropMode() == QAbstractItemView.InternalMove):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.source() is not self or not self._drag_source_path:
            event.ignore()
            return
        target = self.itemAt(event.position().toPoint())
        if target is None:
            self._highlight_target(None)
            self.clearSelection()
            event.ignore()
            return
        self.setCurrentItem(target)
        self._highlight_target(target)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._highlight_target(None)
        self.clearSelection()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if event.source() is not self or self.dragDropMode() != QAbstractItemView.InternalMove:
            event.ignore()
            return
        target = self.itemAt(event.position().toPoint())
        source_path = self._drag_source_path
        target_path = target.data(Qt.UserRole) if target is not None else None
        self._highlight_target(None)
        self.clearSelection()
        if not source_path or not target_path or source_path == target_path:
            event.ignore()
            return
        event.acceptProposedAction()
        # The host updates and rebuilds cards after the drag event completes.
        self.orderRequested.emit(source_path, target_path)

    def begin_handle_drag(self, item):
        if self.dragDropMode() != QAbstractItemView.InternalMove:
            return
        if item is None or self.row(item) < 0:
            return
        self._drag_source_path = item.data(Qt.UserRole)
        self.setCurrentItem(item)
        try:
            self.startDrag(Qt.MoveAction)
        finally:
            self._drag_source_path = None
            self._highlight_target(None)
            self.clearSelection()


class AlbumDragHandle(QLabel):
    """Explicit handle: embedded labels/buttons otherwise consume Qt mouse events."""

    def __init__(self, track_list, parent=None):
        super().__init__('⠿', parent)
        self.track_list = track_list
        self.item = None
        self._press = None
        self.setToolTip('Glisser ici pour réordonner la chanson')
        self.setStyleSheet('font-size:20px;color:#a8a4da;')

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._press is not None and
                event.buttons() & Qt.LeftButton and
                (event.position().toPoint()-self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            self.track_list.begin_handle_drag(self.item)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        super().mouseReleaseEvent(event)


class AlbumABRenderWorker(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, master, analysis_row, output_dir, parent=None, *,
                 mode='match', creative_style='warm', drive=1.0, wet_mix=.2):
        super().__init__(parent)
        self.master=master
        self.analysis_row=dict(analysis_row)
        self.output_dir=output_dir
        self.mode=mode
        self.creative_style=creative_style
        self.drive=drive
        self.wet_mix=wet_mix

    def run(self):
        try:
            if self.mode=='saturation':
                from .album_saturation_preview import render_saturation_preview
                result=render_saturation_preview(
                    self.master,self.analysis_row,self.output_dir,
                    style=self.creative_style,drive=self.drive,mix=self.wet_mix)
            else:
                from .album_tonal_preview import render_tonal_preview
                result=render_tonal_preview(
                    self.master,self.analysis_row,self.output_dir,
                    mode=self.mode,creative_style=self.creative_style)
            self.ready.emit(result)
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class AlbumABDialog(QDialog):
    """Two preloaded WAV players with one visible synchronized A/B transport."""

    def __init__(self, master, analysis, cache, parent=None):
        super().__init__(parent)
        self.master=Path(master).resolve()
        self.analysis=dict(analysis)
        self.cache=Path(cache)
        self.preview=None
        self.worker=None
        self.source='original'
        self._pending_switch=None
        self._switch_generation=0
        self._preview_loaded=False
        self.setWindowTitle('Album A/B · Original / EQ de référence')
        self.setMinimumWidth(560)
        v=QVBoxLayout(self)
        from .album_tonal_preview import preview_decision
        try:
            self.match_decision=preview_decision(self.analysis)
        except (ValueError,TypeError,KeyError):
            self.match_decision={'status':'uncertain','proposal':None}
        self.mode_picker=QComboBox()
        self.mode_picker.addItem('Reference Match · Cohérence',('match',''))
        self.mode_picker.addItem('Creative · Warm',('creative','warm'))
        self.mode_picker.addItem('Creative · Presence',('creative','presence'))
        self.mode_picker.addItem('Creative · Air',('creative','air'))
        self.mode_picker.addItem('Saturation · Tape',('saturation','tape'))
        self.mode_picker.addItem('Saturation · Tube',('saturation','tube'))
        self.mode_picker.addItem('Saturation · Soft Clip',('saturation','softclip'))
        self.mode_picker.currentIndexChanged.connect(self._mode_changed)
        v.addWidget(self.mode_picker)
        self.saturation_options=QWidget(self)
        sat_col=QVBoxLayout(self.saturation_options)
        sat_col.setContentsMargins(0,0,0,0)
        sat_col.setSpacing(5)
        drive_header=QHBoxLayout()
        drive_header.addWidget(QLabel('Drive'))
        self.drive_value=QLabel('1.0')
        drive_header.addWidget(self.drive_value)
        sat_col.addLayout(drive_header)
        self.drive_slider=QSlider(Qt.Horizontal)
        self.drive_slider.setRange(2,25)
        self.drive_slider.setValue(10)
        self.drive_slider.valueChanged.connect(self._saturation_controls_changed)
        sat_col.addWidget(self.drive_slider)
        wet_header=QHBoxLayout()
        wet_header.addWidget(QLabel('Wet Mix'))
        self.wet_value=QLabel('20%')
        wet_header.addWidget(self.wet_value)
        sat_col.addLayout(wet_header)
        self.wet_slider=QSlider(Qt.Horizontal)
        self.wet_slider.setRange(5,40)
        self.wet_slider.setValue(20)
        self.wet_slider.valueChanged.connect(self._saturation_controls_changed)
        sat_col.addWidget(self.wet_slider)
        v.addWidget(self.saturation_options)
        self.status=QLabel('')
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.render_button=QPushButton('✦ Préparer B · Tonal Match')
        self.render_button.clicked.connect(self._prepare)
        v.addWidget(self.render_button)
        controls=QHBoxLayout()
        self.original_button=QPushButton('A · Original')
        self.adjusted_button=QPushButton('B · Tonal Match')
        self.adjusted_button.setEnabled(False)
        self.original_button.clicked.connect(lambda:self._switch('original'))
        self.adjusted_button.clicked.connect(lambda:self._switch('adjusted'))
        controls.addWidget(self.original_button)
        controls.addWidget(self.adjusted_button)
        v.addLayout(controls)
        self.now_playing=QLabel('▶ EN ÉCOUTE : A · ORIGINAL')
        self.now_playing.setAlignment(Qt.AlignCenter)
        self.now_playing.setMinimumHeight(32)
        v.addWidget(self.now_playing)
        playback=QHBoxLayout()
        self.play_button=QPushButton('▶ Écouter / Pause')
        self.play_button.clicked.connect(self._toggle_play)
        playback.addWidget(self.play_button)
        self.position=QLabel('0:00')
        playback.addWidget(self.position)
        v.addLayout(playback)
        self.approve_button=QPushButton('♥ Approuver B pour une future exportation')
        self.approve_button.setEnabled(False)
        self.approve_button.clicked.connect(self._approve)
        v.addWidget(self.approve_button)
        self.note=QLabel('Cette approbation ne remplace pas le master et ne certifie pas la distribution.')
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        # Keep A and B decoded in separate Qt players. Replacing setSource()
        # mid-playback used to stop audio while FFmpeg reloaded the WAV.
        self.audio=QAudioOutput(self)
        self.player=QMediaPlayer(self)  # A, retained for backwards compatibility
        self.player.setAudioOutput(self.audio)
        self.preview_audio=QAudioOutput(self)
        self.preview_player=QMediaPlayer(self)  # B; its source loaded only once ready
        self.preview_player.setAudioOutput(self.preview_audio)
        self.audio.setVolume(1.0)
        self.preview_audio.setVolume(0.0)
        self.player.positionChanged.connect(
            lambda ms: self._position_changed('original',ms))
        self.preview_player.positionChanged.connect(
            lambda ms: self._position_changed('adjusted',ms))
        self.player.playbackStateChanged.connect(
            lambda state: self._playback_changed('original',state))
        self.preview_player.playbackStateChanged.connect(
            lambda state: self._playback_changed('adjusted',state))
        self.preview_player.mediaStatusChanged.connect(self._preview_status_changed)
        self.player.setSource(QUrl.fromLocalFile(str(self.master)))
        self._update_active_indicator()
        self._mode_changed()

    def _saturation_controls_changed(self, *_):
        self.drive_value.setText(f'{self.drive_slider.value()/10:.1f}')
        self.wet_value.setText(f'{self.wet_slider.value()}%')
        if self.worker is None and self.mode_picker.currentData()[0]=='saturation':
            self._mode_changed()

    def _mode_changed(self, *_):
        if self.worker is not None:
            return
        mode,style=self.mode_picker.currentData()
        self.preview=None
        self.adjusted_button.setText(
            'B · Saturation '+style.title() if mode=='saturation'
            else ('B · Creative '+style.title() if mode=='creative'
                  else 'B · Tonal Match'))
        self.saturation_options.setVisible(mode=='saturation')
        self.adjusted_button.setEnabled(False)
        self.approve_button.setEnabled(False)
        if self.source=='adjusted':
            self._switch('original')
        self._pending_switch=None
        self.preview_player.stop()
        self.preview_player.setSource(QUrl())
        self._preview_loaded=False
        self._update_active_indicator()
        if mode=='saturation':
            self.status.setText(
                'Saturation digitale expérimentale : crée des harmoniques et peut '
                'accentuer les artefacts IA. B doit respecter le loudness de A '
                'et le True Peak ≤ −1 dBTP.')
            self.render_button.setText('✦ Préparer B · Saturation '+style.title())
            self.render_button.setEnabled(True)
        elif mode=='creative':
            description={'warm':'plus chaleureux','presence':'plus de présence',
                         'air':'plus d’air et de clarté'}[style]
            self.status.setText(
                f'Alternative créative : {description}. Ce n’est pas une correction '
                'nécessaire, ni une promesse de meilleur son. '
                'B sera égalisé au loudness de A et vérifié en True Peak.')
            self.render_button.setText('✦ Préparer B · Creative '+style.title())
            self.render_button.setEnabled(True)
        else:
            state=self.match_decision['status']
            self.render_button.setText('✦ Préparer B · Tonal Match')
            if state=='already_close':
                self.status.setText(
                    '✓ Déjà proche de la référence : aucune correction EQ justifiée. '
                    'Garde A, ou choisis une alternative Creative pour expérimenter.')
            elif state=='uncertain':
                self.status.setText(
                    '⚠ Comparaison spectrale incertaine : aucun matching EQ automatique. '
                    'Tu peux essayer une couleur Creative, sans la confondre avec un match.')
            else:
                self.status.setText(
                    'Tonal Match disponible : EQ douce selon la comparaison. '
                    'Le loudness A/B et le True Peak seront contrôlés.')
            self.render_button.setEnabled(state=='available')

    def _player_for(self, source):
        return self.player if source=='original' else self.preview_player

    def _audio_for(self, source):
        return self.audio if source=='original' else self.preview_audio

    def _update_active_indicator(self):
        is_a=self.source=='original'
        self.original_button.setStyleSheet(
            'QPushButton {background:#6256be; color:white; border:2px solid #c5b8ff;'
            'border-radius:7px; font-weight:700; padding:9px;}'
            if is_a else '')
        self.adjusted_button.setStyleSheet(
            'QPushButton {background:#6256be; color:white; border:2px solid #c5b8ff;'
            'border-radius:7px; font-weight:700; padding:9px;}'
            if not is_a else '')
        label=('A · ORIGINAL' if is_a else 'B · ' +
               ('CREATIVE '+str((self.preview or {}).get('creative_style','')).upper()
                if (self.preview or {}).get('mode')=='creative'
                else ('SATURATION '+str((self.preview or {}).get('saturation_style','')).upper()
                      if (self.preview or {}).get('mode')=='saturation'
                      else 'TONAL MATCH')))
        self.now_playing.setText('♫ EN ÉCOUTE : '+label)
        self.now_playing.setStyleSheet(
            'color:#edeaff;background:#332d60;border:1px solid #8e81ea;'
            'border-radius:7px;font-weight:700;padding:6px;')
        self.original_button.setAccessibleName('A Original' +
            (' · version active' if is_a else ''))
        self.adjusted_button.setAccessibleName('B Ajusté' +
            (' · version active' if not is_a else ''))

    def _position_changed(self, source, ms):
        if self.source==source:
            self.position.setText(f'{ms//60000}:{(ms//1000)%60:02d}')

    def _playback_changed(self, source, state):
        if state != QMediaPlayer.PlayingState or self._pending_switch != source:
            return
        # The target is playing while muted; now hand off audio and pause
        # the previous decoder. Source files are NEVER reloaded here.
        previous='adjusted' if source=='original' else 'original'
        self._audio_for(previous).setVolume(0.0)
        self._audio_for(source).setVolume(1.0)
        self._player_for(previous).pause()
        self.source=source
        self._pending_switch=None
        self._update_active_indicator()
        self._position_changed(source,self._player_for(source).position())

    def _preview_status_changed(self, status):
        self._preview_loaded=status in (
            QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia)
        # Don't offer switching to B until its WAV decoder is prepared.
        self.adjusted_button.setEnabled(
            self.preview is not None and self._preview_loaded)

    def _toggle_play(self):
        active=self._player_for(self.source)
        if active.playbackState()==QMediaPlayer.PlayingState:
            active.pause()
        else:
            active.play()

    def _switch(self, source):
        if source==self.source:
            # Cancel a pending hand-off if the user taps the current source.
            if self._pending_switch:
                self._player_for(self._pending_switch).pause()
                self._audio_for(self._pending_switch).setVolume(0.0)
                self._pending_switch=None
            self._update_active_indicator()
            return
        if source=='adjusted' and (self.preview is None or not self._preview_loaded):
            return
        previous=self._player_for(self.source)
        target=self._player_for(source)
        pos=previous.position()
        playing=previous.playbackState()==QMediaPlayer.PlayingState
        if self._pending_switch and self._pending_switch!=source:
            self._player_for(self._pending_switch).pause()
            self._audio_for(self._pending_switch).setVolume(0.0)
        self._pending_switch=None
        # Both files have already been loaded. Seek inactive target to the
        # active transport position; never call setSource() during a switch.
        if source=='original':
            self.player.setPosition(pos)
        else:
            self.preview_player.setPosition(pos)
        if playing:
            self._pending_switch=source
            # Keep current player audible until target reports PlayingState.
            self._audio_for(source).setVolume(0.0)
            target.play()
            if target.playbackState()==QMediaPlayer.PlayingState:
                self._playback_changed(source,target.playbackState())
        else:
            self._audio_for(self.source).setVolume(0.0)
            self._audio_for(source).setVolume(1.0)
            self.source=source
            self._update_active_indicator()
            self._position_changed(source,pos)

    def _prepare(self):
        if self.worker is not None:
            return
        mode,style=self.mode_picker.currentData()
        if mode=='match' and self.match_decision['status']!='available':
            self._mode_changed()
            return
        self.render_button.setEnabled(False)
        self.mode_picker.setEnabled(False)
        self.drive_slider.setEnabled(False)
        self.wet_slider.setEnabled(False)
        self.status.setText('Préparation de B, égalisation LUFS et vérification True Peak…')
        worker=AlbumABRenderWorker(
            self.master,self.analysis,self.cache,self,
            mode=mode,creative_style=style or 'warm',
            drive=self.drive_slider.value()/10,
            wet_mix=self.wet_slider.value()/100)
        self.worker=worker
        worker.ready.connect(self._ready)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _ready(self,result):
        self.preview=result
        self.preview_player.stop()
        self.preview_audio.setVolume(0.0)
        self._preview_loaded=False
        self.preview_player.setSource(QUrl.fromLocalFile(str(result['file'])))
        self.adjusted_button.setEnabled(False)  # enabled on LoadedMedia
        self.approve_button.setEnabled(True)
        filters=result.get('eq_filters',[])
        if result.get('mode')=='saturation':
            description=f'Drive {result["drive"]:.2f} · Wet {result["wet_mix"]:.0%}'
            kind='Saturation '+result['saturation_style'].title()
        else:
            description=', '.join(
                f'{p["frequency_hz"]} Hz {p["gain_db"]:+.2f} dB'
                for p in filters)
            kind=('Creative '+str(result.get('creative_style','')).title()
                  if result.get('mode')=='creative' else 'Reference Match')
        intensity=result.get('eq_strength',result.get('intensity',1.0))
        intensity_note=(f' · intensité adaptée {intensity:.0%}' if intensity<1.0
                        else ' · intensité normale')
        self.status.setText(
            f'B prêt ({kind}){intensity_note} : {description} · compensation LUFS {result["gain_db"]:+.2f} dB · '
            f'B {result["measured_lufs"]:.2f} LUFS · '
            f'True Peak {result["verified_true_peak_dbtp"]:.2f} dBTP. '
            'Master original intact; écoute critique requise.')

    def _failed(self,message):
        if 'exceeds the -1 dBTP ceiling' in message:
            self.status.setText(
                '⚠ Le style choisi dépasse encore le True Peak de −1 dBTP '
                'même avec une EQ réduite. A reste intact; essaie Warm ou Air.')
        else:
            self.status.setText('⚠ Aperçu B non créé : '+message+
                                ' · A reste inchangé; essaie une autre proposition.')

    def _worker_finished(self):
        self.worker=None
        self.mode_picker.setEnabled(True)
        self.drive_slider.setEnabled(True)
        self.wet_slider.setEnabled(True)
        if not self.preview:
            mode,_=self.mode_picker.currentData()
            self.render_button.setEnabled(
                mode in ('creative','saturation') or self.match_decision['status']=='available')
        else:
            self.render_button.setEnabled(True)

    def _approve(self):
        if not self.preview:
            return
        import json
        manifest=Path(self.preview['file']).with_suffix('.json')
        data=dict(self.preview,approved=True)
        tmp=manifest.with_suffix('.approved.partial')
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(manifest)
        self.approve_button.setEnabled(False)
        self.note.setText('♥ Aperçu B approuvé pour une future exportation. Le master original reste intact.')

    def closeEvent(self,event):
        if self.worker is not None:
            QMessageBox.information(self,'A/B','Termine la préparation avant de fermer.')
            event.ignore()
            return
        self._pending_switch=None
        self.player.stop()
        self.preview_player.stop()
        super().closeEvent(event)


class AlbumSelectableCard(QFrame):
    """Select or reorder an album song using the non-button area of its card."""

    def __init__(self, select_callback, parent=None):
        super().__init__(parent)
        self._select_callback = select_callback
        self.drag_callback = None
        self._press = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()
            self._select_callback()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._press is not None and self.drag_callback is not None
                and event.buttons() & Qt.LeftButton
                and (event.position().toPoint() - self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            self.drag_callback()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        super().mouseReleaseEvent(event)


class StemInspectWorker(QThread):
    ready=Signal(object)
    failed=Signal(str)

    def __init__(self,config,parent=None):
        super().__init__(parent)
        self.config=config

    def run(self):
        try:
            from .stem_fx_advisor import inspect_and_advise
            self.ready.emit(inspect_and_advise(self.config))
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class StemPreviewWorker(QThread):
    ready=Signal(object)
    failed=Signal(str)

    def __init__(self,source,cache,style,drive,mix,parent=None):
        super().__init__(parent)
        self.source=source
        self.cache=cache
        self.style=style
        self.drive=drive
        self.mix=mix

    def run(self):
        try:
            from .stem_fx_preview import create_stem_preview
            self.ready.emit(create_stem_preview(
                self.source,self.cache,style=self.style,
                drive=self.drive,mix=self.mix))
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class StemPreviewDialog(QDialog):
    """One compact Dry/Wet player. WAVs are prepared before B can be selected."""

    def __init__(self,source,cache,style,drive,mix,parent=None):
        super().__init__(parent)
        self.source=Path(source).resolve()
        self.cache=Path(cache)
        self.style=style
        self.drive=drive
        self.mix=mix
        self.worker=None
        self.wet=None
        self.mode='dry'
        self._ready_to_switch=False
        self._pending=None
        self.setWindowTitle('FRANKENSTEM · Dry / Wet · '+self.source.name)
        self.setMinimumWidth(540)
        layout=QVBoxLayout(self)
        self.info=QLabel('Dry = original. Wet = saturation proposée, nivelée au RMS. '
                         'Aucune modification du stem original.')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        switch=QHBoxLayout()
        self.dry_button=QPushButton('A · DRY')
        self.wet_button=QPushButton('B · WET')
        self.wet_button.setEnabled(False)
        self.dry_button.clicked.connect(lambda:self._switch('dry'))
        self.wet_button.clicked.connect(lambda:self._switch('wet'))
        switch.addWidget(self.dry_button)
        switch.addWidget(self.wet_button)
        layout.addLayout(switch)
        self.active=QLabel('♫ EN ÉCOUTE : A · DRY')
        layout.addWidget(self.active)
        self.transport=QPushButton('▶ Play / Pause')
        self.transport.clicked.connect(self._toggle)
        layout.addWidget(self.transport)
        self.time=QLabel('00:00')
        layout.addWidget(self.time)
        self.audio_a=QAudioOutput(self)
        self.audio_b=QAudioOutput(self)
        self.player_a=QMediaPlayer(self)
        self.player_b=QMediaPlayer(self)
        self.player_a.setAudioOutput(self.audio_a)
        self.player_b.setAudioOutput(self.audio_b)
        self.audio_a.setVolume(1.0)
        self.audio_b.setVolume(0.0)
        self.player_a.positionChanged.connect(
            lambda ms:self._position('dry',ms))
        self.player_b.positionChanged.connect(
            lambda ms:self._position('wet',ms))
        self.player_b.mediaStatusChanged.connect(self._wet_status)
        self.player_a.playbackStateChanged.connect(
            lambda state:self._handoff('dry',state))
        self.player_b.playbackStateChanged.connect(
            lambda state:self._handoff('wet',state))
        self.player_a.setSource(QUrl.fromLocalFile(str(self.source)))
        self._decorate()
        self._prepare()

    def _position(self,mode,ms):
        if self.mode==mode:
            self.time.setText(f'{ms//60000:02d}:{(ms//1000)%60:02d}')

    def _decorate(self):
        is_dry=self.mode=='dry'
        style=('background:#6256be;color:white;border:2px solid #b5a5ff;'
               'border-radius:6px;font-weight:bold;padding:8px;')
        self.dry_button.setStyleSheet(style if is_dry else '')
        self.wet_button.setStyleSheet(style if not is_dry else '')
        self.active.setText('♫ EN ÉCOUTE : '+('A · DRY' if is_dry else 'B · WET'))

    def _wet_status(self,status):
        self._ready_to_switch=(self.wet is not None and status in
            (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia))
        self.wet_button.setEnabled(self._ready_to_switch)

    def _handoff(self,mode,state):
        if self._pending!=mode or state!=QMediaPlayer.PlayingState:
            return
        old='wet' if mode=='dry' else 'dry'
        incoming_audio=self.audio_a if mode=='dry' else self.audio_b
        outgoing_audio=self.audio_b if mode=='dry' else self.audio_a
        outgoing_player=self.player_b if mode=='dry' else self.player_a
        outgoing_audio.setVolume(0.0)
        incoming_audio.setVolume(1.0)
        outgoing_player.pause()
        self.mode=mode
        self._pending=None
        self._decorate()

    def _toggle(self):
        player=self.player_a if self.mode=='dry' else self.player_b
        if player.playbackState()==QMediaPlayer.PlayingState:
            player.pause()
        else:
            player.play()

    def _switch(self,mode):
        if mode==self.mode or (mode=='wet' and not self._ready_to_switch):
            if self._pending and mode==self.mode:
                target=self.player_b if self._pending=='wet' else self.player_a
                target.pause()
                self._pending=None
            return
        outgoing=self.player_a if self.mode=='dry' else self.player_b
        incoming=self.player_a if mode=='dry' else self.player_b
        at=outgoing.position()
        playing=outgoing.playbackState()==QMediaPlayer.PlayingState
        incoming.setPosition(at)
        if playing:
            # Keep current audio audible until the incoming decoder plays.
            self._pending=mode
            if mode=='dry': self.audio_a.setVolume(0.0)
            else: self.audio_b.setVolume(0.0)
            incoming.play()
            if incoming.playbackState()==QMediaPlayer.PlayingState:
                self._handoff(mode,incoming.playbackState())
        else:
            self.audio_a.setVolume(1.0 if mode=='dry' else 0.0)
            self.audio_b.setVolume(1.0 if mode=='wet' else 0.0)
            self.mode=mode
            self._position(mode,at)
            self._decorate()

    def _prepare(self):
        self.info.setText('Préparation de l’aperçu Wet en arrière-plan… '
                          'Tu peux déjà écouter Dry.')
        self.worker=StemPreviewWorker(
            self.source,self.cache,self.style,self.drive,self.mix,self)
        self.worker.ready.connect(self._ready)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _ready(self,result):
        self.wet=result
        self._ready_to_switch=False
        self.wet_button.setEnabled(False)
        self.player_b.setSource(QUrl.fromLocalFile(result['file']))
        self._wet_status(self.player_b.mediaStatus())
        self.info.setText(
            f'Wet prêt : {self.style.title()}, Drive {self.drive:.1f}, '
            f'Mix {self.mix:.0%}. Différence RMS '
            f'{result["rms_difference_db"]:+.2f} dB. '
            'Écoute seulement : pas de QC mastering.')

    def _failed(self,message):
        self.info.setText('⚠ Aucun Wet préparé : '+message+' · Dry reste intact.')

    def _finished(self):
        self.worker=None

    def closeEvent(self,event):
        if self.worker is not None:
            QMessageBox.information(self,'Stem Preview',
                                    'La préparation Wet est en cours.')
            event.ignore()
            return
        self._pending=None
        self.player_a.stop()
        self.player_b.stop()
        super().closeEvent(event)


class StemSaturationDialog(QDialog):
    """User-approved saturation of specific stems, never default-on."""

    def __init__(self, folder, saved, parent=None):
        super().__init__(parent)
        from .stem_mixer import config_template
        from .stem_saturation import suggestions, validated_selections
        self.config=config_template(Path(folder))
        self.saved=validated_selections(self.config,saved)
        self.rows=[]
        self.analysis_worker=None
        self.advice_by_path={}
        self.measured_advice={}
        self.setWindowTitle('FRANKENSTEM · Stem Surgery')
        self.setMinimumWidth(720)
        root=QVBoxLayout(self)
        intro=QLabel('Saturation avant le prémix — à activer séparément pour chaque stem. '
                     'Suggestions heuristiques, pas détection d’artefacts IA.')
        intro.setWordWrap(True)
        root.addWidget(intro)
        self.analyze_button=QPushButton('⌕ Inspecter les stems · FX Advisor')
        self.analyze_button.clicked.connect(self._analyze)
        root.addWidget(self.analyze_button)
        self.summary=QLabel('Analyse non lancée · aucune suggestion audio mesurée.')
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        suggested=QPushButton('✦ Pré-sélectionner voix et basse (à confirmer)')
        suggested.clicked.connect(self._select_safe_suggestions)
        root.addWidget(suggested)
        self.use_inspection=QPushButton('✓ Pré-sélectionner les essais recommandés par mesures')
        self.use_inspection.setEnabled(False)
        self.use_inspection.clicked.connect(self._select_measured_candidates)
        root.addWidget(self.use_inspection)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        inner=QWidget()
        content=QVBoxLayout(inner)
        for advice in suggestions(self.config):
            file=advice['file']
            old=self.saved.get(file,{})
            line=QHBoxLayout()
            enabled=QCheckBox(Path(file).name)
            enabled.setChecked(bool(old.get('enabled',False)))
            line.addWidget(enabled,1)
            style=QComboBox()
            for name in ('tape','tube','softclip'):
                style.addItem(name.title(),name)
            style.setCurrentIndex(max(0,style.findData(old.get('style',advice['style']))))
            line.addWidget(style)
            drive=QDoubleSpinBox()
            drive.setRange(.1,2.5)
            drive.setSingleStep(.1)
            drive.setValue(old.get('drive',advice['drive']))
            drive.setPrefix('Drive ')
            line.addWidget(drive)
            wet=QDoubleSpinBox()
            wet.setRange(1,40)
            wet.setSuffix(' % Wet')
            wet.setValue(old.get('mix',advice['mix'])*100)
            line.addWidget(wet)
            content.addLayout(line)
            note=QLabel(advice['group']+' · '+advice['why'])
            note.setWordWrap(True)
            content.addWidget(note)
            preview=QPushButton('♫ Écouter Dry / Wet')
            preview.clicked.connect(
                lambda _,source=file,st=style,d=drive,w=wet:
                self._preview(source,st,d,w))
            content.addWidget(preview)
            self.rows.append((file,enabled,style,drive,wet))
            self.advice_by_path[file]=note
        content.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll,1)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _analyze(self):
        if self.analysis_worker is not None:
            return
        self.analyze_button.setEnabled(False)
        self.summary.setText('Analyse réelle des stems en cours…')
        worker=StemInspectWorker(self.config,self)
        self.analysis_worker=worker
        worker.ready.connect(self._analysis_ready)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(self._analysis_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _analysis_ready(self,rows):
        candidates=0
        self.measured_advice={row['file']:row['advisor'] for row in rows}
        for row in rows:
            advice=row['advisor']
            if advice['status']=='candidate':
                candidates+=1
            label=self.advice_by_path.get(row['file'])
            if label is not None:
                metrics=advice['evidence']
                marker='✓ Essai possible' if advice['status']=='candidate' else '⚠ Bypass conseillé'
                metric_text=(f' · Crest {metrics.get("median_crest_db")} dB'
                             f' · HF {100*metrics.get("mean_high_frequency_ratio",0):.1f}%'
                             if metrics else '')
                label.setText(marker+metric_text+' · '+advice['reason'])
        self.use_inspection.setEnabled(True)
        self.summary.setText(
            f'Inspection terminée : {len(rows)} stems analysés; '
            f'{candidates} essai(s) envisageable(s). '
            'Aucun traitement activé automatiquement.')

    def _analysis_failed(self,message):
        self.summary.setText('⚠ Inspection impossible : '+message)

    def _analysis_finished(self):
        self.analysis_worker=None
        self.analyze_button.setEnabled(True)

    def _preview(self,source,style,drive,wet):
        if self.analysis_worker is not None:
            QMessageBox.information(self,'Stem Inspector',
                                    'Termine l’inspection avant l’écoute A/B.')
            return
        from pathlib import Path
        root=Path(self.parent().root)
        cache=root/'sound'/'output'/'album_studio'/'stem_fx_previews'
        dlg=StemPreviewDialog(
            source,cache,style.currentData(),drive.value(),wet.value()/100,self)
        dlg.exec()

    def _can_exit(self):
        if self.analysis_worker is not None:
            QMessageBox.information(self,'Stem Inspector',
                                    'Analyse des stems en cours.')
            return False
        return True

    def closeEvent(self,event):
        if not self._can_exit():
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        if self._can_exit():
            super().reject()

    def accept(self):
        if self._can_exit():
            super().accept()

    def _select_measured_candidates(self):
        # Preselect only measured audition candidates, never silence / clipped
        # stems or drums; user must still click OK to approve.
        for file,enabled,style,drive,wet in self.rows:
            status=self.measured_advice.get(file,{})
            enabled.setChecked(status.get('recommendation')=='audition_only')

    def _select_safe_suggestions(self):
        from .auto_mix_candidates import _group
        # Category-only starting points, never unreviewed automatic processing.
        for file,enabled,style,drive,wet in self.rows:
            if _group({'file':file}) in ('vocals','bass'):
                enabled.setChecked(True)

    def _validate_accept(self):
        from .stem_saturation import validated_selections
        selections={}
        for file,enabled,style,drive,wet in self.rows:
            if enabled.isChecked():
                selections[file]={'enabled':True,'style':style.currentData(),
                                  'drive':drive.value(),'mix':round(wet.value()/100,4)}
        try:
            self.selection=validated_selections(self.config,selections)
        except ValueError as exc:
            QMessageBox.warning(self,'Stem Surgery',str(exc))
            return
        self.accept()


class AlbumStudioPage(QWidget):
    """Single guided album workspace that never overwrites individual song sources."""
    backRequested = Signal()
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.project_path = self.root / 'settings' / 'album_project.json'
        self.export_dir = self.root / 'sound' / 'output' / 'album_studio'
        self._worker = None
        self._intelligence_worker = None
        self._recognition_worker = None
        self._release_worker = None
        self._intelligence_report = None
        try:
            self.project = load_project(self.project_path)
        except (OSError, ValueError, json.JSONDecodeError):
            self.project = empty_project()
        self._build()
        self._refresh()
        self._update_external_reference_display()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(12)
        top = QHBoxLayout()
        self.back_btn = QPushButton(self._album_text('← Auto Studio', '← Back to Auto Studio'))
        self.back_btn.clicked.connect(self._back)
        top.addWidget(self.back_btn)
        heading = QLabel('ALBUM STUDIO')
        heading.setStyleSheet('font-size:23px;font-weight:750;background:transparent')
        top.addWidget(heading)
        top.addStretch()
        self.label = QLabel(f'v{APP_VERSION}')
        self.label.setStyleSheet('color:#afb4c9;background:transparent')
        top.addWidget(self.label)
        layout.addLayout(top)
        row = QHBoxLayout()
        self.title = QLineEdit(self.project.get('album','Mon album'))
        self.title.setPlaceholderText(self._album_text('Nom de l’album', 'Album title'))
        self.title.editingFinished.connect(self._save_title)
        row.addWidget(self.title, 1)
        for text, handler in ((self._album_text('Ajouter des WAV', 'Add WAVs'), self._add_wavs),
                              (self._album_text('Ajouter stems', 'Add stems'), self._add_stems),
                              (self._album_text('Importer dossier album', 'Import album folder'), self._add_folder)):
            b = QPushButton(text)
            b.clicked.connect(handler)
            row.addWidget(b)
        layout.addLayout(row)
        self.summary = QLabel()
        self.summary.setStyleSheet('background:transparent;color:#b7c0d1')
        layout.addWidget(self.summary)
        self.album_tools_toggle = QPushButton(self._album_text(
            'Référence et outils d’album', 'Reference and album tools'))
        self.album_tools_toggle.setCheckable(True)
        layout.addWidget(self.album_tools_toggle)
        album_tools = QScrollArea(self)
        album_tools.setWidgetResizable(True)
        album_tools.setFrameShape(QFrame.NoFrame)
        album_tools.setMaximumHeight(280)
        album_tools.hide()
        self.album_tools_toggle.toggled.connect(album_tools.setVisible)
        tools_content = QWidget()
        album_tools.setWidget(tools_content)
        main_layout = layout
        layout = QVBoxLayout(tools_content)
        layout.setContentsMargins(0, 0, 0, 0)
        self.import_master_btn=QPushButton('✓ Reconnaître les masters QC existants (sans remasteriser)')
        self.import_master_btn.setToolTip('Vérification indépendante du WAV et du rapport .qc.json en local.')
        self.import_master_btn.clicked.connect(self._recognize_existing)
        layout.addWidget(self.import_master_btn)
        self.recognition_status=QLabel('Les masters déjà validés sont reconnus avec leur .qc.json. Les autres WAV restent en attente.')
        self.recognition_status.setWordWrap(True)
        self.recognition_status.setStyleSheet('color:#aebbd1;font-size:11px;')
        layout.addWidget(self.recognition_status)
        # Independent audio reference, NOT an album song to process.
        external_row = QHBoxLayout()
        self.external_reference_label = QLabel('Fichier de référence indépendant : aucun')
        self.external_reference_label.setWordWrap(True)
        external_row.addWidget(self.external_reference_label,1)
        self.external_ref_select = QPushButton('♫ Choisir référence WAV / MP3')
        self.external_ref_select.clicked.connect(self._choose_external_reference)
        external_row.addWidget(self.external_ref_select)
        self.external_ref_clear = QPushButton('× Retirer')
        self.external_ref_clear.clicked.connect(self._clear_external_reference)
        external_row.addWidget(self.external_ref_clear)
        layout.addLayout(external_row)
        self.reference_hint = QLabel(
            'Ce fichier sert à guider le choix du prémix puis à comparer les masters finaux. '
            'Il n’est pas ajouté aux pistes de l’album et ne sera jamais remasterisé.')
        self.reference_hint.setWordWrap(True)
        self.reference_hint.setStyleSheet('color:#aebbd1;font-size:11px;')
        layout.addWidget(self.reference_hint)
        reference_row = QHBoxLayout()
        reference_caption = QLabel('Alternative : master QC déjà dans l’album :')
        reference_row.addWidget(reference_caption)
        self.reference_picker = QComboBox()
        self.reference_picker.setToolTip('Choisis une chanson, même si ses stems sont en attente. Le QC reste nécessaire avant la comparaison audio.')
        self.reference_picker.currentIndexChanged.connect(self._reference_changed)
        reference_row.addWidget(self.reference_picker, 1)
        self.compare_album_btn = QPushButton('✦ Analyser la cohérence')
        self.compare_album_btn.clicked.connect(self._analyze_album)
        reference_row.addWidget(self.compare_album_btn)
        layout.addLayout(reference_row)
        self.consistency_status = QLabel('Choisis un WAV externe ou une chanson du projet. La comparaison exige ensuite des masters QC.')
        self.consistency_status.setWordWrap(True)
        self.consistency_status.setStyleSheet('color:#bac5de;background:transparent;font-size:12px;')
        layout.addWidget(self.consistency_status)
        self.advice_legend = QLabel(
            '✦ Conseils d’écoute uniquement — aucun EQ, gain ou master modifié.')
        self.advice_legend.setWordWrap(True)
        self.advice_legend.setStyleSheet('color:#c5b2df;background:transparent;font-size:11px;')
        layout.addWidget(self.advice_legend)
        self.consistency_detail = QLabel('')
        self.consistency_detail.setWordWrap(True)
        self.consistency_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.consistency_detail.setStyleSheet('color:#aebbd1;background:transparent;font-size:11px;')
        self.consistency_detail.setMaximumHeight(88)
        layout.addWidget(self.consistency_detail)
        self.more_results_btn=QPushButton('Afficher tous les détails de l’analyse')
        self.more_results_btn.setCheckable(True)
        self.more_results_btn.toggled.connect(self._toggle_results)
        self.more_results_btn.hide()
        layout.addWidget(self.more_results_btn)
        self.ab_button=QPushButton('♫ Écouter Original / Ajusté (A/B)')
        self.ab_button.setToolTip('Sélectionne une carte de chanson ou clique son bouton A/B pour choisir le master à écouter.')
        self.ab_button.clicked.connect(self._open_ab)
        self.ab_button.setEnabled(False)
        layout.addWidget(self.ab_button)
        layout = main_layout
        self.order_hint = QLabel(self._album_text('⠿ Glisse les cartes pour changer l’ordre.',
                                                '⠿ Drag song cards to reorder.'))
        self.order_hint.setStyleSheet('color:#afbbcf;background:transparent;font-size:11px;')
        layout.addWidget(self.order_hint)
        self.track_list = AlbumOrderList(self)
        self.track_list.setObjectName('albumTrackOrder')
        self.track_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.track_list.setDefaultDropAction(Qt.MoveAction)
        self.track_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.track_list.setSpacing(7)
        self.track_list.setStyleSheet(
            'QListWidget#albumTrackOrder { background:transparent; border:none; }'
            'QListWidget#albumTrackOrder::item {background:transparent; border:none; padding:0;}'
            'QListWidget#albumTrackOrder::item:selected {background:transparent;}')
        self._rebuilding_track_list = False
        self.track_list.orderRequested.connect(self._on_song_card_drop)
        self.track_list.currentItemChanged.connect(self._update_ab_button)
        self.track_list.model().rowsMoved.connect(self._schedule_track_reorder)
        self.track_list.setMinimumHeight(280)
        layout.addWidget(self.track_list, 3)
        layout.addWidget(album_tools)
        self.progress_text = QLabel(self._album_text('Prêt à organiser ton album.', 'Album ready to edit.'))
        self.progress_text.setStyleSheet('background:transparent;color:#b8c4de')
        layout.addWidget(self.progress_text)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.run_btn = QPushButton('✦  AUTO PRODUCE ALBUM — Hermes + 3 variantes')
        self.run_btn.setObjectName('primary')
        self.run_btn.clicked.connect(self._run)
        bottom.addWidget(self.run_btn, 1)
        self.cancel_btn = QPushButton('Annuler')
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.hide()
        bottom.addWidget(self.cancel_btn)
        self.report_btn = QPushButton(self._album_text('Dossier QC', 'QC folder'))
        self.report_btn.clicked.connect(self._open_output)
        bottom.addWidget(self.report_btn)
        self.release_check_btn = QPushButton(self._album_text('Vérifier les masters', 'Release Check'))
        self.release_check_btn.clicked.connect(self._check_release)
        bottom.insertWidget(1, self.release_check_btn)
        layout.addLayout(bottom)
        self.album_eq = QCheckBox(self._album_text(
            'Prochain rendu · EQ correctif Hermes avec Pro-Q 4',
            'Next run · Hermes corrective EQ with Pro-Q 4'))
        self.album_eq.setChecked(self.project.get('album_corrective_eq_enabled') is True)
        self.album_eq.toggled.connect(self._set_album_eq)
        layout.addWidget(self.album_eq)

    @staticmethod
    def _album_text(french, english):
        return english if get_language() == 'en' else french

    def _card_status(self, track):
        status = track.get('status', 'waiting')
        result = track.get('result') or {}
        if status in ('qc_pass', 'needs_review') and not Path(result.get('file') or '.').is_file():
            return self._album_text('Master introuvable', 'Master missing'), '#f2bb8d'
        if status == 'qc_pass':
            return self._album_text('Master vérifié', 'Master verified'), '#a6e2bd'
        if status == 'needs_review':
            return self._album_text('QC à vérifier', 'Review QC'), '#f2bb8d'
        if status == 'error':
            return self._album_text('Rendu en échec', 'Render failed'), '#ff9f9f'
        if result or track.get('error'):
            return self._album_text('À refaire', 'Needs a new render'), '#f2bb8d'
        return self._album_text('En attente', 'Waiting'), '#b3b9c8'

    def _set_album_eq(self, enabled):
        self.project['album_corrective_eq_enabled'] = enabled
        self._save()

    def _busy(self):
        return bool(self._release_worker is not None
                    or (self._worker is not None and self._worker.isRunning())
                    or (self._intelligence_worker is not None
                        and self._intelligence_worker.isRunning())
                    or (self._recognition_worker is not None
                        and self._recognition_worker.isRunning()))

    def _album_track_for_path(self, source):
        if not source:
            return None
        return next((row for row in self.project['tracks']
                     if row['path']==source), None)

    def _ab_track_ready(self, source):
        if self._busy() or self._intelligence_report is None:
            return False
        row=self._album_track_for_path(source)
        if row is None:
            return False
        result=row.get('result') or {}
        if (row.get('status')!='qc_pass' or result.get('status')!='qc_pass'
                or not result.get('file') or not Path(result['file']).is_file()):
            return False
        report_rows=self._intelligence_report.get('tracks',[])
        index=self.project['tracks'].index(row)
        return (index<len(report_rows) and
                report_rows[index].get('status')=='measured')

    def _select_song(self, source):
        if self._busy():
            return
        for i in range(self.track_list.count()):
            item=self.track_list.item(i)
            if item.data(Qt.UserRole)==source:
                self.track_list.setCurrentItem(item)
                self._update_ab_button()
                return

    def _update_ab_button(self,*_):
        selected=self.track_list.currentItem()
        source=selected.data(Qt.UserRole) if selected is not None else None
        self.ab_button.setEnabled(self._ab_track_ready(source))
        track=self._album_track_for_path(source)
        self.ab_button.setText(
            '♫ A/B · '+track['title'] if track else
            '♫ Sélectionne une chanson pour écouter A/B')

    def _open_ab(self):
        selected=self.track_list.currentItem()
        source=selected.data(Qt.UserRole) if selected is not None else None
        self._open_ab_for_song(source)

    def _open_ab_for_song(self, source):
        # Resolve the requested source path directly. Never rely on a stale
        # QListWidget selection or a numerical row index after reordering.
        if not self._ab_track_ready(source):
            QMessageBox.information(
                self,'Album A/B',
                'Choisis une chanson dont le master QC a été analysé. '
                'Lance d’abord Analyser la cohérence.')
            return
        row=self._album_track_for_path(source)
        index=self.project['tracks'].index(row)
        analysis=self._intelligence_report['tracks'][index]
        master=(row['result'] or {})['file']
        self._select_song(source)
        dlg=AlbumABDialog(master,analysis,self.export_dir/'ab_previews',self)
        dlg.setWindowTitle('Album A/B · '+row['title'])
        dlg.exec()

    def _toggle_results(self, expanded):
        self.consistency_detail.setMaximumHeight(16777215 if expanded else 88)
        self.more_results_btn.setText(
            'Réduire les détails de l’analyse' if expanded
            else 'Afficher tous les détails de l’analyse')

    def _reference_mode(self):
        mode=self.project.get('album_reference_mode')
        if mode in ('external','album'):
            return mode
        # Migrated projects: a standalone reference used to take priority.
        return 'external' if self.project.get('external_reference_wav') else 'album'

    def _reference_message(self):
        mode=self._reference_mode()
        if mode=='external':
            external=self._external_reference()
            if external:
                return 'Référence active : WAV externe — '+external.name
            return '⚠ Référence externe indisponible. Choisis un WAV valide.'
        choice=self.reference_picker.currentData()
        if choice is None:
            return 'Choisis une chanson du projet ou un WAV externe.'
        track=next((t for t in self.project['tracks'] if t['path']==choice[1]), None)
        if track is None:
            return 'Référence de l’album introuvable.'
        if track.get('status')!='qc_pass':
            return 'Référence sélectionnée : '+track['title']+' · stems/mixage en attente de master QC.'
        return 'Référence sélectionnée : '+track['title']+' · master QC disponible.'

    def _stem_fx_for(self, source):
        if self._busy():
            return
        track=self._album_track_for_path(source)
        if track is None or track['kind']!='stems':
            return
        try:
            dialog=StemSaturationDialog(track['path'],track.get('stem_saturation'),self)
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'Stem Surgery',str(exc))
            return
        if dialog.exec()!=QDialog.Accepted:
            return
        if dialog.selection == (track.get('stem_saturation') or {}):
            return
        track['stem_saturation']=dialog.selection
        track['status']='waiting'
        track['error']='Stem FX modifiés — relance Auto Produce pour un nouveau QC.'
        self._intelligence_report=None
        self.consistency_detail.clear()
        self._save()
        self._refresh()

    def _live_fx_for(self, source):
        if self._busy():
            return
        track=self._album_track_for_path(source)
        if not track or track['kind']!='stems':
            return
        try:
            from .live_stem_ui import LiveStemDialog
            dialog=LiveStemDialog(self.root,track['path'],
                                  track.get('stem_saturation'), self,
                                  de_sizzle=track.get('stem_de_sizzle'))
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'FRANKENSTEM Live',str(exc))
            return
        if dialog.exec()!=QDialog.Accepted:
            return
        if (dialog.selection == (track.get('stem_saturation') or {})
                and dialog.de_sizzle == (track.get('stem_de_sizzle') or {})):
            return
        track['stem_saturation']=dialog.selection
        track['status']='waiting'
        track['stem_de_sizzle'] = dialog.de_sizzle
        track['error']='Live FX approuvés — relance Auto Produce pour mastering QC.'
        self._intelligence_report=None
        self.consistency_detail.clear()
        self._save()
        self._refresh()

    def _recognize_existing(self):
        if self._busy():
            return
        paths=[t['path'] for t in self.project['tracks']
               if t['kind']=='stereo' and t.get('status')!='qc_pass']
        if not paths:
            self.recognition_status.setText('Aucun WAV en attente de vérification.')
            return
        worker=MasterRecognitionWorker(paths,self)
        self._recognition_worker=worker
        worker.item.connect(self._recognition_result)
        worker.finished_scan.connect(self._recognition_done)
        worker.finished.connect(self._recognition_finished)
        worker.finished.connect(worker.deleteLater)
        self.import_master_btn.setEnabled(False)
        self.recognition_status.setText('Vérification locale des WAV et QC…')
        worker.start()

    def _recognition_result(self,path,result,error):
        for track in self.project['tracks']:
            if track['kind']=='stereo' and track['path']==path:
                if result is not None:
                    track['result']=result
                    track['status']='qc_pass'
                    track['error']=''
                else:
                    track['error']='QC import : '+error
                    track['status']='waiting'
                break
        self._save()
        self._refresh()

    def _recognition_done(self,success,total):
        self.recognition_status.setText(
            f'{success}/{total} master(s) reconnus et vérifiés · '
            f'{total-success} en attente de QC ou de rapport valide.')

    def _recognition_finished(self):
        self._recognition_worker=None
        self._refresh()

    def _external_reference(self):
        raw = self.project.get('external_reference_wav')
        if not raw:
            return None
        try:
            from .album_external_reference import validate_external_reference
            return validate_external_reference(raw)
        except (OSError,ValueError):
            return None

    def _update_external_reference_display(self):
        ref=self._external_reference()
        if ref:
            self.external_reference_label.setText('Référence audio : '+ref.name)
            self.external_ref_clear.setEnabled(not self._busy())
        else:
            self.external_reference_label.setText(
                '⚠ Référence audio absente ou invalide'
                if self.project.get('external_reference_wav') else
                'Fichier de référence indépendant : aucun')
            self.external_ref_clear.setEnabled(
                bool(self.project.get('external_reference_wav')) and not self._busy())
        self.external_ref_select.setEnabled(not self._busy())
        text = self._album_text('Référence et outils d’album', 'Reference and album tools')
        if ref and self._reference_mode() == 'external':
            text += ' · ' + ref.name
        self.album_tools_toggle.setText(text)
        choice=self.reference_picker.currentData()
        active_external=(self._reference_mode()=='external')
        album_ok=False
        if choice is not None:
            track=next((x for x in self.project['tracks'] if x['path']==choice[1]),None)
            result=(track or {}).get('result') or {}
            album_ok=bool(track and track.get('status')=='qc_pass'
                          and result.get('status')=='qc_pass'
                          and Path(result.get('file') or '').is_file())
        ready=(ref is not None) if active_external else album_ok
        self.compare_album_btn.setEnabled(ready and not self._busy()
                                           and any(t.get('status')=='qc_pass' for t in self.project['tracks']))
        if self._intelligence_report is None:
            self.consistency_status.setText(self._reference_message())

    def _choose_external_reference(self):
        if self._busy():
            return
        selected,_=QFileDialog.getOpenFileName(
            self,'Choisir un fichier de référence indépendant','','Audio de référence (*.wav *.mp3)')
        if not selected:
            return
        try:
            from .album_external_reference import validate_external_reference
            path=validate_external_reference(selected)
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'Référence audio',str(exc))
            return
        self.project['external_reference_wav']=str(path)
        self.project['album_reference_mode']='external'
        self._save()
        self._intelligence_report=None
        self.consistency_detail.clear()
        self.more_results_btn.hide()
        self._update_ab_button()
        self._update_external_reference_display()

    def _clear_external_reference(self):
        if self._busy():
            return
        self.project.pop('external_reference_wav',None)
        self.project['album_reference_mode']='album'
        self._save()
        self._intelligence_report=None
        self.consistency_detail.clear()
        self.more_results_btn.hide()
        self._update_ab_button()
        self._update_external_reference_display()

    def _refresh_reference_picker(self):
        tracks = self.project['tracks']
        selected_path = self.project.get('reference_source')
        self.reference_picker.blockSignals(True)
        self.reference_picker.clear()
        self.reference_picker.addItem('— Choisir une chanson —', None)
        for i, track in enumerate(tracks):
            result = track.get('result') or {}
            available = (track.get('status') == 'qc_pass'
                         and result.get('status') == 'qc_pass'
                         and isinstance(result.get('file'), str)
                         and Path(result['file']).is_file())
            # Always selectable: the selection is a plan for the future
            # master even while stems are waiting. QC gates analysis, not choice.
            self.reference_picker.addItem(
                track.get('title','') + ('' if available else ' · à produire'),
                (i, track['path']))
            if track['path'] == selected_path:
                self.reference_picker.setCurrentIndex(self.reference_picker.count()-1)
        self.reference_picker.blockSignals(False)
        self._update_external_reference_display()

    def _reference_changed(self, _):
        if self._busy():
            return
        choice = self.reference_picker.currentData()
        self.project['reference_source'] = choice[1] if choice else None
        if choice is not None:
            self.project['album_reference_mode']='album'
        self._save()
        self._intelligence_report = None
        self.consistency_detail.clear()
        self.more_results_btn.hide()
        self._update_external_reference_display()

    def _analyze_album(self):
        if self._busy():
            return
        choice = self.reference_picker.currentData()
        external = self._external_reference() if self._reference_mode()=='external' else None
        if self._reference_mode()=='external' and self.project.get('external_reference_wav') and external is None:
            QMessageBox.warning(self, 'Référence audio',
                'Le fichier de référence enregistré est introuvable ou invalide. '
                'Choisis un autre WAV ou MP3, ou retire cette référence.')
            return
        if external is None:
            if choice is None:
                QMessageBox.information(self,'Album Intelligence',
                                        'Choisis un WAV, un MP3 ou une chanson.')
                return
            row=self.project['tracks'][choice[0]]
            result=row.get('result') or {}
            if row.get('status')!='qc_pass' or result.get('status')!='qc_pass':
                QMessageBox.information(self,'Album Intelligence',
                    'La chanson est sélectionnée, mais son master QC n’est pas encore prêt. '
                    'Produis-la avant l’analyse.')
                return
        self._save_title()
        worker = AlbumIntelligenceWorker(
            self.project, choice[0] if choice and external is None else None, self,
            external_reference_wav=str(external) if external else None)
        self._intelligence_worker = worker
        worker.completed.connect(self._album_analyzed)
        worker.failed.connect(self._album_analysis_failed)
        worker.finished.connect(self._intelligence_finished)
        worker.finished.connect(worker.deleteLater)
        self.compare_album_btn.setEnabled(False)
        self.consistency_status.setText('Analyse locale des masters en cours…')
        worker.start()

    def _intelligence_finished(self):
        self._intelligence_worker = None
        self._refresh_reference_picker()

    def _album_analysis_failed(self, message):
        self.consistency_status.setText('Analyse impossible : ' + message)

    def _album_analyzed(self, report):
        # A deterministic review-only advisor. Never touch the mastering
        # pipeline or silently write suggested plugin settings.
        try:
            advice = advise_album(report)
        except (ValueError, TypeError, KeyError) as exc:
            self._album_analysis_failed('Album Match Advisor : ' + str(exc))
            return
        self._intelligence_report = report
        self._update_ab_button()
        self._album_advice = advice
        self.export_dir.mkdir(parents=True,exist_ok=True)
        target = self.export_dir / 'album_consistency.json'
        tmp = target.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(target)
        advice_path = self.export_dir / 'album_match_advice.json'
        advice_tmp = advice_path.with_suffix('.json.tmp')
        advice_tmp.write_text(json.dumps(advice,ensure_ascii=False,indent=2),encoding='utf-8')
        advice_tmp.replace(advice_path)
        lang = get_language()
        self.advice_legend.setText(
            '✦ Listening suggestions only — no EQ, gain or master modified.'
            if lang == 'en' else
            '✦ Conseils d’écoute uniquement — aucun EQ, gain ou master modifié.')
        items = report['tracks']
        measured = sum(r['status'] in ('reference','measured') for r in items)
        flagged = sum(bool(r.get('flags')) for r in items)
        summary=(f'Référence : {report["reference_title"]} · '
                 f'{measured}/{len(items)} masters analysés · {flagged} piste(s) à écouter')
        if measured==0:
            summary += ' · Lance AUTO PRODUCE ALBUM pour créer les masters QC.'
        self.consistency_status.setText(summary)
        lines = []
        for row in items:
            flags = row.get('flags',[])
            if row['status']=='not_ready':
                info = 'master QC requis'
            elif row['status']=='analysis_error':
                info = 'analyse impossible : ' + row.get('note','')
            else:
                diffs = row.get('relative_band_delta_db',[])
                dominant = max((abs(x) for x in diffs),default=0)
                info = (f'Δ LUFS {row["lufs_delta"]:+.2f} · '
                        f'écart spectral maximal {dominant:.1f} dB'
                        + (' · ⚠ Écoute conseillée' if flags else ' · Mesures proches'))
            suggestion = localized_card(advice['tracks'][row['index']], lang)
            lines.append(f'{row["index"]+1:02d}. {row["title"]}: {info}'
                         + ('\n    ↳ ' + suggestion if suggestion else ''))
        self.consistency_detail.setText('\n'.join(lines))
        self.more_results_btn.setVisible(len(lines)>2 and measured>0)
        self.more_results_btn.setChecked(False)
        if measured==0:
            self.consistency_detail.setText(
                f'{len(items)} chanson(s) en attente de master QC. '
                'Elles sont bien importées : lance Auto Produce Album.')



    def _save(self):
        save_project(self.project_path, self.project)

    def _save_title(self):
        if not self._busy():
            self.project['album'] = self.title.text().strip() or 'Mon album'
            self._save()

    def _add(self, items):
        if self._busy() or not items:
            return
        errors = []
        count = 0
        for path, kind in items:
            try: count += add_entries(self.project, [path], kind)
            except (OSError, ValueError) as exc: errors.append(f'{Path(path).name}: {exc}')
        if count:
            self._save()
            self._refresh()
            # An existing QC sidecar triggers read-only verification automatically.
            # For fresh or unmastered WAVs no action is taken; there is never
            # an implicit FFmpeg render or Auto Master here.
            if any(kind=='stereo' and Path(path).with_suffix('.qc.json').is_file()
                   for path,kind in items):
                self._recognize_existing()
        if errors:
            QMessageBox.warning(self, 'Fichiers ignorés', '\n'.join(errors[:8]))

    def _add_wavs(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Ajouter des chansons stéréo', '', 'WAV (*.wav)')
        self._add([(f,'stereo') for f in files])

    def _add_stems(self):
        folder = QFileDialog.getExistingDirectory(self, 'Sélectionner le dossier stems d’une chanson')
        if folder: self._add([(folder,'stems')])

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Sélectionner le dossier album')
        if folder:
            try: self._add(discover_album(folder))
            except (OSError, ValueError) as exc: QMessageBox.warning(self, 'Import impossible', str(exc))

    def _move(self, index, offset):
        if self._busy(): return
        nxt = index + offset
        tracks = self.project['tracks']
        if not 0 <= nxt < len(tracks): return
        tracks[index], tracks[nxt] = tracks[nxt], tracks[index]
        self._save(); self._refresh()

    def _remove(self, index):
        if self._busy(): return
        self.project['tracks'].pop(index)
        self._save(); self._refresh()

    def _on_song_card_drop(self, source_path, target_path):
        if self._busy():
            return
        QTimer.singleShot(0, lambda: self._move_song_onto(source_path, target_path))

    def _move_song_onto(self, source_path, target_path):
        if self._busy() or self._rebuilding_track_list:
            return
        try:
            changed = move_track_onto(self.project, source_path, target_path)
        except ValueError as exc:
            QMessageBox.warning(self, 'Ordre de l’album', str(exc))
            return
        if changed:
            self._save()
            self._intelligence_report = None
            self.consistency_detail.clear()
            self._refresh()

    def _schedule_track_reorder(self, *_):
        # Qt emits rowsMoved as it performs the internal drag; read the
        # final model order once the drop event finishes.
        if not self._rebuilding_track_list:
            QTimer.singleShot(0, self._commit_track_reorder)

    def _commit_track_reorder(self):
        if self._busy() or self._rebuilding_track_list:
            return
        ordered = [self.track_list.item(i).data(Qt.UserRole)
                   for i in range(self.track_list.count())]
        current = [track['path'] for track in self.project['tracks']]
        if ordered == current:
            return
        try:
            reorder_tracks(self.project, ordered)
        except ValueError as exc:
            QMessageBox.warning(self, 'Ordre de l’album', str(exc))
            self._refresh()
            return
        self._save()
        self._intelligence_report = None
        self.consistency_detail.clear()
        self._refresh()

    def _refresh(self):
        self._rebuilding_track_list = True
        previous=self.track_list.currentItem()
        selected_path=previous.data(Qt.UserRole) if previous is not None else None
        self.track_list._hovered_item = None
        self.track_list.clear()
        tracks = self.project['tracks']
        for i, track in enumerate(tracks):
            path=track['path']
            card = AlbumSelectableCard(lambda source=path: self._select_song(source))
            card.setToolTip('Clique pour sélectionner cette chanson ou glisse sa carte pour changer l’ordre.')
            card.setStyleSheet('QFrame { background:#1b1d29;border:1px solid #3a3d50;border-radius:9px }'
                               'QLabel {background:transparent;border:none}')
            line = QHBoxLayout(card)
            line.setContentsMargins(12, 8, 12, 8)
            number = QLabel(str(i+1).zfill(2))
            number.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            number.setStyleSheet('color:#9ea5b8;background:transparent')
            line.addWidget(number)
            info = QVBoxLayout()
            name = QLabel(track['title'])
            name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            name.setStyleSheet('font-size:14px;font-weight:650;background:transparent')
            status, color = self._card_status(track)
            heading = QHBoxLayout()
            heading.addWidget(name, 1)
            badge = QLabel(status)
            badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            badge.setStyleSheet(f'color:{color};font-size:11px;font-weight:650;')
            heading.addWidget(badge)
            info.addLayout(heading)

            result = track.get('result') or {}
            parts = []
            if track.get('status') in ('qc_pass', 'needs_review') and Path(result.get('file') or '.').is_file():
                selected = result.get('album_selected_candidate')
                if selected:
                    parts.append({'balanced': 'Balanced', 'vocal-focus': 'Vocal Focus',
                                  'punchy': 'Punchy'}.get(selected, selected))
                eq = result.get('album_corrective_eq')
                if eq:
                    parts.append(self._album_text('EQ Hermes appliqué', 'Hermes EQ applied')
                                 if eq.get('moves') else
                                 self._album_text('EQ Hermes : aucun ajustement', 'Hermes EQ: no adjustment'))
                else:
                    parts.append(self._album_text('Sans EQ Hermes', 'No Hermes EQ recorded'))
            if track.get('error'):
                parts.append(track['error'])
            if not parts:
                parts.append('Stems' if track['kind'] == 'stems' else self._album_text('WAV stéréo', 'Stereo WAV'))
            detail = QLabel(' · '.join(parts)[:150])
            detail.setStyleSheet('color:#b3b9c8;font-size:11px;background:transparent')
            detail.setWordWrap(True)
            detail.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            info.addWidget(detail)
            line.addLayout(info, 1)

            ab_track_button = QPushButton('A/B')
            ab_track_button.setEnabled(self._ab_track_ready(path))
            ab_track_button.setToolTip(self._album_text(
                'Analyse la cohérence du master pour activer A/B.',
                'Run the album consistency analysis on the master to enable A/B.'))
            ab_track_button.clicked.connect(lambda _, source=path: self._open_ab_for_song(source))
            line.addWidget(ab_track_button)
            if track['kind'] == 'stems':
                live_btn = QPushButton('Live FX')
                live_btn.setEnabled(not self._busy())
                live_btn.clicked.connect(lambda _, source=path: self._live_fx_for(source))
                line.addWidget(live_btn)

            more = QPushButton('⋯')
            more.setAccessibleName(self._album_text('Actions pour cette chanson', 'Song actions'))
            more.setFixedWidth(34)
            more.setEnabled(not self._busy())
            menu = QMenu(more)
            if isinstance(result.get('album_ai_decisions'), dict):
                menu.addAction(self._album_text('IA · décisions de mix', 'AI mix decisions'),
                               lambda checked=False, n=i: self._show_ai_decisions(n))
            if isinstance(result.get('album_ai_selection'), dict):
                menu.addAction(self._album_text('Choix IA du prémix', 'AI mix selection'),
                               lambda checked=False, n=i: self._show_ai_selection(n))
            if len(result.get('album_candidates') or {}) == 3:
                menu.addAction(self._album_text('Ouvrir les 3 WAV', 'Open the 3 WAVs'),
                               lambda checked=False, n=i: self._open_candidates(n))
            if track['kind'] == 'stems':
                menu.addAction('FX Stems', lambda checked=False, source=path: self._stem_fx_for(source))
            menu.addAction(self._album_text('Retirer de l’album', 'Remove from album'),
                           lambda checked=False, n=i: self._remove(n))
            more.setMenu(menu)
            line.addWidget(more)
            drag_handle = AlbumDragHandle(self.track_list, card)
            line.addWidget(drag_handle)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, track['path'])
            item.setSizeHint(card.sizeHint())
            self.track_list.addItem(item)
            drag_handle.item = item
            card.drag_callback = lambda item=item: self.track_list.begin_handle_drag(item)
            self.track_list.setItemWidget(item, card)
        if selected_path:
            for index in range(self.track_list.count()):
                item=self.track_list.item(index)
                if item.data(Qt.UserRole)==selected_path:
                    self.track_list.setCurrentItem(item)
                    break
        self._rebuilding_track_list = False
        self.track_list.setDragEnabled(not self._busy())
        self.track_list.setAcceptDrops(not self._busy())
        self.track_list.setDragDropMode(
            QAbstractItemView.InternalMove if not self._busy()
            else QAbstractItemView.NoDragDrop)
        nstereo = sum(t['kind']=='stereo' for t in tracks)
        nstems = len(tracks) - nstereo
        self.summary.setText(self._album_text(
            f'{len(tracks)} chansons · {nstereo} WAV stéréo · {nstems} projets stems',
            f'{len(tracks)} songs · {nstereo} stereo WAVs · {nstems} stem projects'))
        self.release_check_btn.setEnabled(bool(tracks) and not self._busy())
        self.album_eq.setEnabled(not self._busy())
        self.run_btn.setEnabled(bool(tracks) and not self._busy())
        self.back_btn.setEnabled(not self._busy())
        self.import_master_btn.setEnabled(not self._busy() and any(
            t['kind']=='stereo' and t.get('status')!='qc_pass'
            for t in self.project['tracks']))
        self._refresh_reference_picker()
        self._update_ab_button()

    def _run(self):
        if self._busy(): return
        self._save_title()
        rows = [(i, dict(row)) for i,row in enumerate(self.project['tracks'])]
        if not rows:
            QMessageBox.information(self, 'Album vide', 'Ajoute au moins une chanson pour commencer.')
            return
        from .reference_learning import library_path
        external = self._external_reference() if self._reference_mode()=='external' else None
        if self._reference_mode()=='external' and self.project.get('external_reference_wav') and external is None:
            QMessageBox.warning(self, 'Référence audio',
                'Le fichier de référence est manquant ou invalide. '
                'Change la référence avant Auto Produce Album.')
            return
        if self._reference_mode()=='album':
            choice=self.reference_picker.currentData()
            if choice is not None:
                row=next((x for x in self.project['tracks'] if x['path']==choice[1]),None)
                result=(row or {}).get('result') or {}
                candidate=result.get('file')
                if (row is not None and row.get('status')=='qc_pass'
                        and result.get('status')=='qc_pass' and candidate
                        and Path(candidate).is_file()):
                    external=Path(candidate)
                else:
                    self.progress_text.setText(
                        'Référence d’album sélectionnée, mais master QC en attente : '
                        'prémix guidé par les préférences habituelles.')
        eq_plugin = None
        if self.album_eq.isChecked():
            from .plugin_registry import selected_proq4

            eq_plugin = selected_proq4(self.root / 'settings/vst_roles.json')
            if eq_plugin is None:
                QMessageBox.warning(self, 'EQ album', 'Configure Pro-Q 4 comme EQ correctif dans Plugins.')
                return
        self._worker = AlbumBatchWorker(
            rows, self.export_dir, self,
            reference_path=library_path(self.root),
            external_reference_wav=str(external) if external else None,
            eq_root=self.root, eq_plugin=eq_plugin)
        self._worker.item.connect(self._item_result)
        self._worker.stage.connect(self._progress)
        self._worker.done.connect(self._done)
        self._worker.finished.connect(self._refresh)
        self.run_btn.setEnabled(False)
        self.cancel_btn.show()
        self.cancel_btn.setEnabled(True)
        self.back_btn.setEnabled(False)
        self.progress.setFormat(self._album_text('Production · %p%', 'Production · %p%'))
        self.progress.show()
        self.progress.setValue(0)
        self.progress_text.setText('Préparation de la file de traitement…')
        self._refresh()
        self._worker.start()

    def _item_result(self, index, status, result, error):
        if index >= len(self.project['tracks']): return
        row = self.project['tracks'][index]
        row['status'] = status
        row['result'] = result
        row['error'] = error
        self._save(); self._refresh()

    def _progress(self, completed, total, message):
        self.progress.setValue(int(100 * completed / max(1,total)))
        self.progress_text.setText(message)

    def _done(self, cancelled):
        self.cancel_btn.hide()
        self.back_btn.setEnabled(True)
        self.progress_text.setText('Traitement annulé — progression sauvegardée.' if cancelled else
                                   'File terminée — vérifie les rapports QC avant distribution.')
        self._save()
        self.export_dir.mkdir(parents=True,exist_ok=True)
        (self.export_dir / 'album_report.json').write_text(
            json.dumps(album_summary(self.project), ensure_ascii=False, indent=2), encoding='utf-8')
        self._refresh()

    def _cancel(self):
        if self._release_worker is not None:
            self._release_worker.stop.set()
            self.cancel_btn.setEnabled(False)
            self.progress_text.setText('Annulation du contrôle…')
            return
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.progress_text.setText('Annulation demandée…')

    def _show_ai_decisions(self, index):
        if not 0 <= index < len(self.project['tracks']):
            return
        details = (self.project['tracks'][index].get('result') or {}).get('album_ai_decisions') or {}
        if details.get('mode') == 'hermes':
            plan = details.get('plan', {})
            lines = [f'Modèle local : {details.get("model", "Hermes")}', '',
                     'Ajustements de gain proposés par groupe (en dB) :']
            for variant in ('balanced', 'vocal-focus', 'punchy'):
                groups = plan.get(variant, {})
                lines.append(f'{variant}: ' + ', '.join(f'{k} {v:+.2f}' for k,v in groups.items()))
            lines += ['', 'Mesures DSP échantillonnées, pas des LUFS intégrés.',
                      'Aucun effet VST3 appliqué automatiquement dans cette version.']
        else:
            lines = ['Le plan IA n’a pas été utilisé. Les 3 variantes conservatrices ont été produites.',
                     '', 'Raison : ' + str(details.get('reason', 'Indéterminée'))]
        QMessageBox.information(self, 'AI Producer Brain — rapport', '\n'.join(lines))

    def _show_ai_selection(self, index):
        if not 0 <= index < len(self.project['tracks']):
            return
        report = (self.project['tracks'][index].get('result') or {}).get('album_ai_selection') or {}
        metrics = report.get('metrics') or {}
        lines = [f"Mix masterisé : {report.get('selected', 'balanced')}",
                 'Mode : ' + ('Hermes local' if report.get('mode') == 'hermes' else 'Secours Balanced'),
                 'Raison : ' + str(report.get('reason', 'Non disponible')), '',
                 'Mesures DSP complètes par fichier (pas LUFS ni true peak) :']
        for name in ('balanced', 'vocal-focus', 'punchy'):
            row = metrics.get(name, {})
            if row:
                lines.append(f"{name} : RMS {row.get('rms_dbfs')} dBFS | crête {row.get('sample_peak_dbfs')} dBFS | "
                             f"crest {row.get('crest_db')} dB | corr {row.get('stereo_correlation')}")
        lines += ['', 'La décision doit être confirmée à l’écoute avant publication.']
        QMessageBox.information(self, 'AI Mix Evaluation', '\n'.join(lines))

    def _open_candidates(self, index):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if not 0 <= index < len(self.project['tracks']):
            return
        result = self.project['tracks'][index].get('result') or {}
        candidates = result.get('album_candidates') or {}
        folder = Path(candidates.get('balanced', '')).parent if candidates.get('balanced') else None
        if folder is None or not folder.is_dir():
            QMessageBox.warning(self, 'Variantes introuvables', 'Les fichiers ont été déplacés ou supprimés.')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _check_release(self):
        if self._busy() or not self.project['tracks']:
            return
        tracks = json.loads(json.dumps(self.project['tracks']))
        target = self.export_dir / 'album_release_check.json'
        worker = AlbumReleaseCheckWorker(tracks, target, self)
        self._release_worker = worker
        worker.progress.connect(lambda done, total, title:
                                self._progress(done, total, 'Contrôle WAV · ' + title))
        worker.completed.connect(self._release_check_completed)
        worker.finished.connect(self._release_check_finished)
        worker.finished.connect(worker.deleteLater)
        self.cancel_btn.show()
        self.cancel_btn.setEnabled(True)
        self.progress.setFormat(self._album_text('Contrôle sortie · %p%', 'Release check · %p%'))
        self.progress.show()
        self.progress.setValue(0)
        self._refresh()
        worker.start()

    def _release_check_completed(self, report, error):
        if report is None:
            self.progress_text.setText(error)
            return
        from .album_release_check import format_album_release

        self.progress.setValue(100)
        self.progress_text.setText('Contrôle terminé · album_release_check.json')
        dialog = QDialog(self)
        dialog.setWindowTitle('Contrôle des masters avant sortie')
        dialog.resize(640, 480)
        layout = QVBoxLayout(dialog)
        details = QPlainTextEdit(dialog)
        details.setReadOnly(True)
        details.setPlainText(format_album_release(report))
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setModal(True)
        dialog.show()

    def _release_check_finished(self):
        self._release_worker = None
        self.cancel_btn.hide()
        self._refresh()

    def _open_output(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        self.export_dir.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.export_dir)))

    def _back(self):
        if self._busy():
            QMessageBox.information(self, 'Traitement en cours', 'Annule le traitement avant de revenir à Auto Studio.')
            return
        self._save_title()
        self.backRequested.emit()

    def shutdown(self):
        if self._release_worker is not None:
            self._release_worker.stop.set()
            self._release_worker.wait()
        if self._busy():
            if self._worker is not None and self._worker.isRunning():
                self._worker.cancel()
                self._worker.wait(5000)
            if self._intelligence_worker is not None and self._intelligence_worker.isRunning():
                self._intelligence_worker.wait(5000)
            if self._recognition_worker is not None and self._recognition_worker.isRunning():
                self._recognition_worker.wait(5000)
