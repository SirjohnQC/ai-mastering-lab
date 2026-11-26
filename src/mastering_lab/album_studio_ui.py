"""Album Studio — WAV batch mastering and evaluated stem mix candidates."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QComboBox, QFileDialog, QMessageBox, QProgressBar, QScrollArea,
    QListWidget, QListWidgetItem, QAbstractItemView, QApplication, QDialog)

from .album_project import (empty_project, load_project, save_project,
                            add_entries, discover_album, album_summary, reorder_tracks, move_track_onto)
from .album_match_advisor import advise_album, localized_card
from .ui_language import get_language
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class AlbumBatchWorker(QThread):
    item = Signal(int, str, object, str)  # index, status, QC result, error
    stage = Signal(int, int, str)          # number finished, total, message
    done = Signal(bool)                   # cancelled

    def __init__(self, entries, target, parent=None, *, reference_path=None, external_reference_wav=None):
        super().__init__(parent)
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
        count = len(self.entries)
        finished = 0
        for idx, row in self.entries:
            if self.stop_event.is_set():
                break
            if can_reuse_master(row, external_reference_wav=self.external_reference_wav):
                self.item.emit(idx, 'qc_pass', row.get('result'), '')
            elif (row['kind'] == 'stems' and not Path(row['path']).is_dir()) or (row['kind'] == 'stereo' and not Path(row['path']).is_file()):
                self.item.emit(idx, 'error', None, 'Source audio introuvable')
            else:
                try:
                    if row['kind'] == 'stems':
                        result = master_stem_folder(row['path'], self.target, stop=self.stop_event,
                            progress=lambda message, completed=finished: self.stage.emit(completed, count, message),
                            reference_path=self.reference_path,
                            external_reference_wav=self.external_reference_wav)
                    else:
                        self.stage.emit(finished, count, 'Mastering : ' + row['title'])
                        result = rename_album_master(dict(master_song(row['path'], self.target, stop=self.stop_event)), row['title'])
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
                 mode='match', creative_style='warm'):
        super().__init__(parent)
        self.master=master
        self.analysis_row=dict(analysis_row)
        self.output_dir=output_dir
        self.mode=mode
        self.creative_style=creative_style

    def run(self):
        try:
            from .album_tonal_preview import render_tonal_preview
            self.ready.emit(render_tonal_preview(
                self.master,self.analysis_row,self.output_dir,
                mode=self.mode,creative_style=self.creative_style))
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
        self.mode_picker.currentIndexChanged.connect(self._mode_changed)
        v.addWidget(self.mode_picker)
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

    def _mode_changed(self, *_):
        if self.worker is not None:
            return
        mode,style=self.mode_picker.currentData()
        self.preview=None
        self.adjusted_button.setEnabled(False)
        self.approve_button.setEnabled(False)
        if self.source=='adjusted':
            self._switch('original')
        self._pending_switch=None
        self.preview_player.stop()
        self.preview_player.setSource(QUrl())
        self._preview_loaded=False
        self._update_active_indicator()
        if mode=='creative':
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
                else 'TONAL MATCH'))
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
        self.status.setText('Préparation de B, égalisation LUFS et vérification True Peak…')
        worker=AlbumABRenderWorker(
            self.master,self.analysis,self.cache,self,
            mode=mode,creative_style=style or 'warm')
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
        description=', '.join(
            f'{p["frequency_hz"]} Hz {p["gain_db"]:+.2f} dB'
            for p in filters)
        kind=('Creative '+str(result.get('creative_style','')).title()
              if result.get('mode')=='creative' else 'Reference Match')
        self.status.setText(
            f'B prêt ({kind}) : {description} · compensation LUFS {result["gain_db"]:+.2f} dB · '
            f'B {result["measured_lufs"]:.2f} LUFS · '
            f'True Peak {result["verified_true_peak_dbtp"]:.2f} dBTP. '
            'Master original intact; écoute critique requise.')

    def _failed(self,message):
        self.status.setText('⚠ Aperçu B non créé : '+message+
                            ' · A reste inchangé; essaie une autre proposition.')

    def _worker_finished(self):
        self.worker=None
        self.mode_picker.setEnabled(True)
        if not self.preview:
            mode,_=self.mode_picker.currentData()
            self.render_button.setEnabled(
                mode=='creative' or self.match_decision['status']=='available')
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
    """Clicking non-button portions selects the corresponding album song."""

    def __init__(self, select_callback, parent=None):
        super().__init__(parent)
        self._select_callback = select_callback

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._select_callback()
            event.accept()
        else:
            super().mousePressEvent(event)


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
        self.back_btn = QPushButton('←  Retour à Auto Studio')
        self.back_btn.clicked.connect(self._back)
        top.addWidget(self.back_btn)
        heading = QLabel('ALBUM STUDIO')
        heading.setStyleSheet('font-size:23px;font-weight:750;background:transparent')
        top.addWidget(heading)
        top.addStretch()
        self.label = QLabel('v0.26.1 · Smart A/B Creative')
        self.label.setStyleSheet('color:#afb4c9;background:transparent')
        top.addWidget(self.label)
        layout.addLayout(top)
        caption = QLabel('Les dossiers stems utilisent des mesures DSP et Hermes local pour proposer des gains prudents pour Balanced / Vocal Focus / Punchy. En cas d’échec, variantes de secours. Hermes évalue ensuite les trois WAV et sélectionne un candidat (secours : Balanced).')
        caption.setWordWrap(True)
        caption.setStyleSheet('background:transparent;color:#abb5c8')
        layout.addWidget(caption)
        row = QHBoxLayout()
        self.title = QLineEdit(self.project.get('album','Mon album'))
        self.title.setPlaceholderText('Nom de l’album')
        self.title.editingFinished.connect(self._save_title)
        row.addWidget(self.title, 1)
        for text, handler in (('Ajouter des WAV', self._add_wavs),
                              ('Ajouter stems', self._add_stems),
                              ('Importer dossier album', self._add_folder)):
            b = QPushButton(text)
            b.clicked.connect(handler)
            row.addWidget(b)
        layout.addLayout(row)
        self.summary = QLabel()
        self.summary.setStyleSheet('background:transparent;color:#b7c0d1')
        layout.addWidget(self.summary)
        self.import_master_btn=QPushButton('✓ Reconnaître les masters QC existants (sans remasteriser)')
        self.import_master_btn.setToolTip('Vérification indépendante du WAV et du rapport .qc.json en local.')
        self.import_master_btn.clicked.connect(self._recognize_existing)
        layout.addWidget(self.import_master_btn)
        self.recognition_status=QLabel('Les masters déjà validés sont reconnus avec leur .qc.json. Les autres WAV restent en attente.')
        self.recognition_status.setWordWrap(True)
        self.recognition_status.setStyleSheet('color:#aebbd1;font-size:11px;')
        layout.addWidget(self.recognition_status)
        # Independent WAV reference, NOT an album song to process.
        external_row = QHBoxLayout()
        self.external_reference_label = QLabel('WAV de référence indépendant : aucun')
        self.external_reference_label.setWordWrap(True)
        external_row.addWidget(self.external_reference_label,1)
        self.external_ref_select = QPushButton('♫ Choisir WAV de référence')
        self.external_ref_select.clicked.connect(self._choose_external_reference)
        external_row.addWidget(self.external_ref_select)
        self.external_ref_clear = QPushButton('× Retirer')
        self.external_ref_clear.clicked.connect(self._clear_external_reference)
        external_row.addWidget(self.external_ref_clear)
        layout.addLayout(external_row)
        self.reference_hint = QLabel(
            'Ce WAV sert à guider le choix du prémix puis à comparer les masters finaux. '
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
        self.order_hint = QLabel('⠿ Glisse une chanson directement SUR une autre carte pour changer son ordre.')
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
        self.progress_text = QLabel('Prêt à organiser ton album.')
        self.progress_text.setStyleSheet('background:transparent;color:#b8c4de')
        layout.addWidget(self.progress_text)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
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
        self.report_btn = QPushButton('Ouvrir le dossier QC')
        self.report_btn.clicked.connect(self._open_output)
        bottom.addWidget(self.report_btn)
        layout.addLayout(bottom)
        foot = QLabel('Décisions Hermes limitées aux gains de groupes (±1 dB), sans FX automatiques. Hermes propose le mix à masteriser (secours : Balanced). '
                      'La cohérence artistique de l’album reste à développer.')
        foot.setWordWrap(True)
        foot.setStyleSheet('background:transparent;color:#a0aabd;font-size:12px')
        layout.addWidget(foot)

    def _busy(self):
        return bool((self._worker is not None and self._worker.isRunning())
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
            self.external_reference_label.setText('WAV de référence : '+ref.name)
            self.external_ref_clear.setEnabled(not self._busy())
        else:
            self.external_reference_label.setText(
                '⚠ Référence WAV absente ou invalide'
                if self.project.get('external_reference_wav') else
                'WAV de référence indépendant : aucun')
            self.external_ref_clear.setEnabled(
                bool(self.project.get('external_reference_wav')) and not self._busy())
        self.external_ref_select.setEnabled(not self._busy())
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
            self,'Choisir un WAV de référence indépendant','','Stereo WAV (*.wav)')
        if not selected:
            return
        try:
            from .album_external_reference import validate_external_reference
            path=validate_external_reference(selected)
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'Référence WAV',str(exc))
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
            QMessageBox.warning(self, 'Référence WAV',
                'Le WAV de référence enregistré est introuvable ou invalide. '
                'Choisis un autre WAV ou retire cette référence.')
            return
        if external is None:
            if choice is None:
                QMessageBox.information(self,'Album Intelligence',
                                        'Choisis un WAV indépendant ou une chanson.')
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
            card.setToolTip('Clique pour sélectionner cette chanson; glisse ⠿ pour changer l’ordre.')
            card.setStyleSheet('QFrame { background:#1b1d29;border:1px solid #3a3d50;border-radius:9px }'
                               'QLabel {background:transparent;border:none}')
            line = QHBoxLayout(card)
            line.setContentsMargins(12, 8, 12, 8)
            number = QLabel(str(i+1).zfill(2))
            number.setStyleSheet('color:#9ea5b8;background:transparent')
            line.addWidget(number)
            info = QVBoxLayout()
            name = QLabel(track['title'])
            name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            name.setStyleSheet('font-size:14px;font-weight:650;background:transparent')
            status = track.get('status', 'waiting')
            kind = 'Stems · mixage requis' if track['kind']=='stems' else 'WAV stéréo'
            detail = QLabel(f'{kind}   ·   {status}' + (f"  ·  {track['error'][:90]}" if track.get('error') else '') + ('  ·  3 variantes WAV disponibles' if (track.get('result') or {}).get('album_candidates') else ''))
            detail.setStyleSheet('color:#b3b9c8;font-size:11px;background:transparent')
            detail.setWordWrap(True)
            detail.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            result = track.get('result') or {}
            selected = result.get('album_selected_candidate')
            selection = result.get('album_ai_selection') or {}
            if selected:
                label = {'balanced': 'Balanced', 'vocal-focus': 'Vocal Focus', 'punchy': 'Punchy'}.get(selected, selected)
                mode = '✦ Choix IA' if selection.get('mode') == 'hermes' else '⚠ Choix secours'
                choice = QLabel(f'{mode} : {label}  →  Master')
                choice.setStyleSheet('color:#a6e2bd;font-size:12px;font-weight:650;background:transparent')
                choice.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                info.addWidget(name)
                info.addWidget(choice)
                detail.setText(detail.text() + f'  ·  Master : {label}')
            ai_mode = (track.get('result') or {}).get('album_ai_decisions', {}).get('mode')
            if ai_mode:
                detail.setText(detail.text() + ('  ·  Hermes ✓' if ai_mode == 'hermes' else '  ·  IA secours'))
            if not selected:
                info.addWidget(name)
            info.addWidget(detail)
            line.addLayout(info, 1)
            variants = (track.get('result') or {}).get('album_candidates') or {}
            ai_decisions = (track.get('result') or {}).get('album_ai_decisions')
            if isinstance(ai_decisions, dict):
                ai_button = QPushButton('🧠  IA' if ai_decisions.get('mode') == 'hermes' else '⚠  Secours')
                ai_button.setToolTip('Voir le détail des décisions ou la raison du mode de secours')
                ai_button.setEnabled(not self._busy())
                ai_button.clicked.connect(lambda _, n=i: self._show_ai_decisions(n))
                line.addWidget(ai_button)
            selection = (track.get('result') or {}).get('album_ai_selection')
            if isinstance(selection, dict):
                select_btn = QPushButton('🎯  Choix IA' if selection.get('mode') == 'hermes' else '🎯  Choix secours')
                select_btn.setEnabled(not self._busy())
                select_btn.clicked.connect(lambda _, n=i: self._show_ai_selection(n))
                line.addWidget(select_btn)
            if len(variants) == 3:
                view = QPushButton('♫  3 WAV')
                view.setToolTip('Ouvrir le dossier des trois variantes enregistrées')
                view.setEnabled(not self._busy())
                view.clicked.connect(lambda _, n=i: self._open_candidates(n))
                line.addWidget(view)
            if self._ab_track_ready(path):
                ab_track_button=QPushButton('♫ A/B')
                ab_track_button.setToolTip('Comparer le master de '+track['title'])
                ab_track_button.clicked.connect(
                    lambda _, source=path: self._open_ab_for_song(source))
                line.addWidget(ab_track_button)
            drag_handle = AlbumDragHandle(self.track_list, card)
            line.addWidget(drag_handle)
            for text, cb in (('×', lambda _, n=i: self._remove(n)),):
                button = QPushButton(text)
                button.setFixedWidth(32)
                button.setEnabled(not self._busy())
                button.clicked.connect(cb)
                line.addWidget(button)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, track['path'])
            item.setSizeHint(card.sizeHint())
            self.track_list.addItem(item)
            drag_handle.item = item
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
        self.summary.setText(f'{len(tracks)} chansons · {nstereo} WAV stéréo · {nstems} projets stems')
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
            QMessageBox.warning(self, 'Référence WAV',
                'Le WAV de référence est manquant ou invalide. '
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
        self._worker = AlbumBatchWorker(
            rows, self.export_dir, self,
            reference_path=library_path(self.root),
            external_reference_wav=str(external) if external else None)
        self._worker.item.connect(self._item_result)
        self._worker.stage.connect(self._progress)
        self._worker.done.connect(self._done)
        self._worker.finished.connect(self._refresh)
        self.run_btn.setEnabled(False)
        self.cancel_btn.show()
        self.cancel_btn.setEnabled(True)
        self.back_btn.setEnabled(False)
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
        if self._busy():
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
        if self._busy():
            if self._worker is not None and self._worker.isRunning():
                self._worker.cancel()
                self._worker.wait(5000)
            if self._intelligence_worker is not None and self._intelligence_worker.isRunning():
                self._intelligence_worker.wait(5000)
            if self._recognition_worker is not None and self._recognition_worker.isRunning():
                self._recognition_worker.wait(5000)
