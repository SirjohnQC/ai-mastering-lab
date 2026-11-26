"""Album Studio — WAV batch mastering and evaluated stem mix candidates."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QLineEdit, QComboBox, QFileDialog, QMessageBox, QProgressBar, QScrollArea)

from .album_project import (empty_project, load_project, save_project,
                            add_entries, discover_album, album_summary)
from .album_match_advisor import advise_album, localized_card
from .ui_language import get_language


class AlbumBatchWorker(QThread):
    item = Signal(int, str, object, str)  # index, status, QC result, error
    stage = Signal(int, int, str)          # number finished, total, message
    done = Signal(bool)                   # cancelled

    def __init__(self, entries, target, parent=None, *, reference_path=None):
        super().__init__(parent)
        self.entries = entries
        self.target = Path(target)
        self.reference_path = reference_path
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
            if can_reuse_master(row):
                self.item.emit(idx, 'qc_pass', row.get('result'), '')
            elif (row['kind'] == 'stems' and not Path(row['path']).is_dir()) or (row['kind'] == 'stereo' and not Path(row['path']).is_file()):
                self.item.emit(idx, 'error', None, 'Source audio introuvable')
            else:
                try:
                    if row['kind'] == 'stems':
                        result = master_stem_folder(row['path'], self.target, stop=self.stop_event,
                            progress=lambda message, completed=finished: self.stage.emit(completed, count, message),
                            reference_path=self.reference_path)
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

    def __init__(self, project, reference_index, parent=None):
        super().__init__(parent)
        self.project_snapshot = json.loads(json.dumps(project))
        self.reference_index = reference_index

    def run(self):
        from .album_intelligence import compare_album
        try:
            self.completed.emit(compare_album(
                self.project_snapshot, reference_index=self.reference_index))
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


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
        self.label = QLabel('v0.25.2 · Smart Master Import')
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
        reference_row = QHBoxLayout()
        reference_caption = QLabel('Référence d’album (master QC) :')
        reference_row.addWidget(reference_caption)
        self.reference_picker = QComboBox()
        self.reference_picker.setToolTip('Ton propre master validé sert à comparer l’album. Distinct des références musicales de Reference Learning.')
        self.reference_picker.currentIndexChanged.connect(self._reference_changed)
        reference_row.addWidget(self.reference_picker, 1)
        self.compare_album_btn = QPushButton('✦ Analyser la cohérence')
        self.compare_album_btn.clicked.connect(self._analyze_album)
        reference_row.addWidget(self.compare_album_btn)
        layout.addLayout(reference_row)
        self.consistency_status = QLabel('Choisis une référence avec un master QC validé.')
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
        layout.addWidget(self.consistency_detail)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setStyleSheet('QScrollArea {background:transparent;border:none}')
        self.holder = QWidget()
        self.holder.setStyleSheet('background:transparent')
        self.rows = QVBoxLayout(self.holder)
        self.rows.setSpacing(6)
        self.rows.setAlignment(Qt.AlignTop)
        scroller.setWidget(self.holder)
        layout.addWidget(scroller, 1)
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
            self.reference_picker.addItem(
                track.get('title','') + ('' if available else ' · QC requis'),
                (i, track['path']) if available else None)
            if not available:
                item_index = self.reference_picker.count()-1
                self.reference_picker.model().item(item_index).setEnabled(False)
            if available and track['path'] == selected_path:
                self.reference_picker.setCurrentIndex(self.reference_picker.count()-1)
        self.reference_picker.blockSignals(False)
        self.compare_album_btn.setEnabled(
            self.reference_picker.currentData() is not None and not self._busy())

    def _reference_changed(self, _):
        if self._busy():
            return
        choice = self.reference_picker.currentData()
        self.project['reference_source'] = choice[1] if choice else None
        self._save()
        self._intelligence_report = None
        self.consistency_detail.clear()
        self.compare_album_btn.setEnabled(bool(choice))

    def _analyze_album(self):
        if self._busy():
            return
        choice = self.reference_picker.currentData()
        if choice is None:
            QMessageBox.information(self,'Album Intelligence',
                                    'Choisis une chanson dont le master a réussi le QC.')
            return
        self._save_title()
        worker = AlbumIntelligenceWorker(self.project, choice[0], self)
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
        self.consistency_status.setText(
            f'Référence : {report["reference_title"]} · '
            f'{measured}/{len(items)} masters analysés · {flagged} piste(s) à écouter')
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

    def _refresh(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        tracks = self.project['tracks']
        for i, track in enumerate(tracks):
            card = QFrame()
            card.setStyleSheet('QFrame { background:#1b1d29;border:1px solid #3a3d50;border-radius:9px }'
                               'QLabel {background:transparent;border:none}')
            line = QHBoxLayout(card)
            line.setContentsMargins(12, 8, 12, 8)
            number = QLabel(str(i+1).zfill(2))
            number.setStyleSheet('color:#9ea5b8;background:transparent')
            line.addWidget(number)
            info = QVBoxLayout()
            name = QLabel(track['title'])
            name.setStyleSheet('font-size:14px;font-weight:650;background:transparent')
            status = track.get('status', 'waiting')
            kind = 'Stems · mixage requis' if track['kind']=='stems' else 'WAV stéréo'
            detail = QLabel(f'{kind}   ·   {status}' + (f"  ·  {track['error'][:90]}" if track.get('error') else '') + ('  ·  3 variantes WAV disponibles' if (track.get('result') or {}).get('album_candidates') else ''))
            detail.setStyleSheet('color:#b3b9c8;font-size:11px;background:transparent')
            detail.setWordWrap(True)
            result = track.get('result') or {}
            selected = result.get('album_selected_candidate')
            selection = result.get('album_ai_selection') or {}
            if selected:
                label = {'balanced': 'Balanced', 'vocal-focus': 'Vocal Focus', 'punchy': 'Punchy'}.get(selected, selected)
                mode = '✦ Choix IA' if selection.get('mode') == 'hermes' else '⚠ Choix secours'
                choice = QLabel(f'{mode} : {label}  →  Master')
                choice.setStyleSheet('color:#a6e2bd;font-size:12px;font-weight:650;background:transparent')
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
            for text, cb in (('↑', lambda _, n=i: self._move(n,-1)),
                             ('↓', lambda _, n=i: self._move(n,1)),
                             ('×', lambda _, n=i: self._remove(n))):
                button = QPushButton(text)
                button.setFixedWidth(32)
                button.setEnabled(not self._busy())
                button.clicked.connect(cb)
                line.addWidget(button)
            self.rows.addWidget(card)
        nstereo = sum(t['kind']=='stereo' for t in tracks)
        nstems = len(tracks) - nstereo
        self.summary.setText(f'{len(tracks)} chansons · {nstereo} WAV stéréo · {nstems} projets stems')
        self.run_btn.setEnabled(bool(tracks) and not self._busy())
        self.back_btn.setEnabled(not self._busy())
        self.import_master_btn.setEnabled(not self._busy() and any(
            t['kind']=='stereo' and t.get('status')!='qc_pass'
            for t in self.project['tracks']))
        self._refresh_reference_picker()

    def _run(self):
        if self._busy(): return
        self._save_title()
        rows = [(i, dict(row)) for i,row in enumerate(self.project['tracks'])]
        if not rows:
            QMessageBox.information(self, 'Album vide', 'Ajoute au moins une chanson pour commencer.')
            return
        from .reference_learning import library_path
        self._worker = AlbumBatchWorker(rows, self.export_dir, self,
                                       reference_path=library_path(self.root))
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
