"""Compact local reference library UI for Auto Studio and Album Mode."""
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QListWidget, QListWidgetItem, QMessageBox)
from .reference_learning import (library_path, load_library, save_library,
                                 add_reference, extract_features)


class ReferenceWorker(QThread):
    ready = Signal(str, object, str)
    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
    def run(self):
        try:
            self.ready.emit(self.source, extract_features(self.source), '')
        except Exception as exc:
            self.ready.emit(self.source, None, str(exc))


class ReferenceLibraryDialog(QDialog):
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Reference Learning — Inspiration sonore (local)')
        self.setMinimumWidth(560)
        self.path = library_path(root)
        self.library = load_library(self.path)
        self.worker = None
        layout = QVBoxLayout(self)
        info = QLabel('INSPIRATION SONORE — WAV/FLAC/MP3 analysés localement. '
                      'Les références actives peuvent influencer les propositions Hermes de sélection de mix '
                      'et les propositions AI FX/EQ; elles ne modifient pas directement Auto Master '
                      'et ne servent pas de chanson de référence pour un album. '
                      'Aucun entraînement du modèle ni copie du son.')
        info.setWordWrap(True)
        layout.addWidget(info)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._changed)
        layout.addWidget(self.list)
        actions = QHBoxLayout()
        self.add = QPushButton('＋ Ajouter des références')
        self.add.clicked.connect(self._add)
        self.remove = QPushButton('× Retirer la sélection')
        self.remove.clicked.connect(self._remove)
        actions.addWidget(self.add)
        actions.addWidget(self.remove)
        layout.addLayout(actions)
        self.status = QLabel('Les sources originales ne sont jamais modifiées.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QPushButton('Terminé')
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._refresh()

    def _refresh(self):
        from PySide6.QtCore import Qt
        self.list.blockSignals(True)
        self.list.clear()
        active = set(self.library['active'])
        for entry in self.library['entries']:
            f = entry['features']
            path = entry['path']
            title = f"{Path(path).name}   ·   crest {f['crest_db']:+.1f} dB · {f['sample_rate']} Hz"
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if path in active else Qt.Unchecked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.status.setText(f"{len(active)} référence(s) actives / {len(self.library['entries'])} importée(s). "
                            'Profil spectral moyen disponible pour les décisions Hermes compatibles; aucun entraînement.')

    def _changed(self, _item):
        from PySide6.QtCore import Qt
        self.library['active'] = [self.list.item(i).data(Qt.UserRole)
             for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked]
        save_library(self.path, self.library)
        self._refresh()

    def _add(self):
        if self.worker is not None:
            return
        files, _ = QFileDialog.getOpenFileNames(self, 'Fichiers de référence', '',
                        'Audio compatible (*.wav *.flac *.mp3);;Tous les fichiers (*)')
        if not files:
            return
        self.pending = iter(files)
        self.add.setEnabled(False)
        self._next()

    def _next(self):
        source = next(self.pending, None)
        if source is None:
            self.add.setEnabled(True)
            self.status.setText('Analyse terminée. Références sauvegardées.')
            return
        self.status.setText('Analyse locale : ' + Path(source).name)
        self.worker = ReferenceWorker(source, self)
        self.worker.ready.connect(self._done)
        self.worker.start()

    def _done(self, source, features, error):
        if error:
            QMessageBox.warning(self, 'Référence ignorée', f'{Path(source).name}: {error}')
        else:
            self.library = add_reference(self.library, source, features)
            save_library(self.path, self.library)
            self._refresh()
        worker = self.worker
        self.worker = None
        worker.wait()
        worker.deleteLater()
        self._next()

    def _remove(self):
        from PySide6.QtCore import Qt
        current = self.list.currentItem()
        if current is None:
            return
        path = current.data(Qt.UserRole)
        self.library['entries'] = [x for x in self.library['entries'] if x['path'] != path]
        self.library['active'] = [x for x in self.library['active'] if x != path]
        save_library(self.path, self.library)
        self._refresh()

    def accept(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, 'Analyse en cours', 'Termine l’analyse avant de fermer cette fenêtre.')
            return
        super().accept()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, 'Analyse en cours', 'Termine l’analyse avant de fermer cette fenêtre.')
            return
        super().reject()
