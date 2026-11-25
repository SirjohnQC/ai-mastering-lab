"""Local Ollama preferences and explicit connectivity/model smoke tests.

Tests run in a Qt worker thread. Never uploads user audio or scans local files.
"""
from __future__ import annotations
import base64
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QPushButton, QPlainTextEdit, QProgressBar, QMessageBox)

DEFAULT_TEXT = 'hermes3:8b'
DEFAULT_VISION = 'qwen3-vl:4b'


def read_ai_preferences(root: Path) -> dict:
    path = Path(root) / 'settings' / 'ai_review.json'
    try:
        cfg = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not isinstance(cfg, dict):
            cfg = {}
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault('model', DEFAULT_TEXT)
    cfg.setdefault('vision_model', DEFAULT_VISION)
    return cfg


def save_ai_preferences(root: Path, text_model: str, vision_model: str) -> None:
    if not text_model.strip() or not vision_model.strip():
        raise ValueError('Sélectionne deux modèles installés.')
    path = Path(root) / 'settings' / 'ai_review.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = read_ai_preferences(root)
    cfg.update({'model': text_model, 'vision_model': vision_model})
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')


def ollama_request(url: str, payload=None, timeout: float=15) -> dict:
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    request = Request(url, data=body, headers={'Content-Type':'application/json', 'Accept':'application/json'},
                      method='POST' if body is not None else 'GET')
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(1_000_000)
    except HTTPError as exc:
        detail = exc.read(1200).decode('utf-8', errors='replace')
        raise RuntimeError(f'HTTP {exc.code}: {detail}') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f'Connexion/délai Ollama: {exc}') from exc
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError('Ollama a répondu sans JSON valide: '+raw[:180].decode('utf-8', errors='replace')) from exc
    if not isinstance(result, dict):
        raise RuntimeError('Réponse Ollama inattendue.')
    if result.get('error'):
        raise RuntimeError(str(result['error'])[:500])
    return result


def test_ollama(target: str, model: str|None=None, *, requester=ollama_request) -> str:
    base = 'http://127.0.0.1:11434'
    if target == 'server':
        tags = requester(base+'/api/tags', timeout=5)
        if not isinstance(tags.get('models'), list):
            raise RuntimeError('Serveur disponible, mais /api/tags ne retourne pas les modèles attendus.')
        return f'Connexion OK : {len(tags["models"])} modèles installés.'
    tags = requester(base+'/api/tags', timeout=5)
    names = [x.get('name') or x.get('model') for x in tags.get('models', []) if isinstance(x, dict)]
    if model not in names:
        raise RuntimeError(f'Modèle absent de Ollama : {model}')
    if target == 'text':
        payload = {'model':model, 'stream':False, 'messages':[{'role':'user','content':'Réponds exactement avec le mot OK.'}],
                   'think':False, 'options':{'num_predict':256}}
    elif target == 'vision':
        # Two-color test image is sufficient to test actual multimodal image input.
        from PIL import Image, ImageDraw
        picture=Image.new('RGB',(128,96),'#e01b24')
        draw=ImageDraw.Draw(picture)
        draw.rectangle((64,0,127,95),fill='#205cdb')
        stream=io.BytesIO()
        picture.save(stream,format='PNG')
        payload={'model':model,'stream':False,'think':False,
                 'messages':[{'role':'user','content':'Image rouge et bleue: cite seulement les deux couleurs, sans explication.',
                              'images':[base64.b64encode(stream.getvalue()).decode('ascii')]}],
                 'options':{'num_predict':3072,'temperature':0}}
    else:
        raise ValueError(target)
    response = requester(base+'/api/chat', payload, timeout=150)
    content = (response.get('message') or {}).get('content','')
    if not str(content).strip():
        raise RuntimeError(f'Modèle chargé, mais réponse finale vide (done_reason={response.get("done_reason")}, thinking={bool((response.get("message") or {}).get("thinking"))}). Le modèle peut ignorer think=false.')
    return f'{model} : réponse OK — {str(content).strip()[:100]}'


class _TestWorker(QObject):
    finished = Signal(str, str, str)
    def __init__(self, target, model):
        super().__init__()
        self.target, self.model = target, model
    @Slot()
    def run(self):
        try:
            self.finished.emit(self.target, test_ollama(self.target, self.model), '')
        except Exception as exc:
            self.finished.emit(self.target, '', str(exc))


class AISettingsDialog(QDialog):
    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root=Path(root)
        self.setWindowTitle('Settings — Ollama & AI Models')
        self.resize(600, 360)
        self._thread=None;self._worker=None
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Ollama local : http://127.0.0.1:11434 — les tests n’envoient aucun fichier audio.'))
        self.text_model=QComboBox();self.vision_model=QComboBox()
        self.text_model.setEditable(False);self.vision_model.setEditable(False)
        layout.addWidget(QLabel('Modèle texte / mix evaluator'))
        layout.addWidget(self.text_model)
        layout.addWidget(QLabel('Modèle vision / spectrogrammes'))
        layout.addWidget(self.vision_model)
        row=QHBoxLayout()
        self.refresh_btn=QPushButton('↻ Refresh models')
        self.server_btn=QPushButton('Test Ollama')
        self.text_btn=QPushButton('Test text model')
        self.vision_btn=QPushButton('Test vision model')
        for b in (self.refresh_btn,self.server_btn,self.text_btn,self.vision_btn):row.addWidget(b)
        layout.addLayout(row)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status=QLabel('Ready');layout.addWidget(self.status)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);layout.addWidget(self.log)
        actions=QHBoxLayout()
        self.save_btn=QPushButton('Save settings')
        self.close_btn=QPushButton('Close')
        actions.addWidget(self.save_btn);actions.addWidget(self.close_btn)
        layout.addLayout(actions)
        self.refresh_btn.clicked.connect(self.refresh_models)
        self.server_btn.clicked.connect(lambda:self.start_test('server'))
        self.text_btn.clicked.connect(lambda:self.start_test('text'))
        self.vision_btn.clicked.connect(lambda:self.start_test('vision'))
        self.save_btn.clicked.connect(self.save)
        self.close_btn.clicked.connect(self.accept)
        self.refresh_models()

    def refresh_models(self):
        from .ollama_models import installed_models
        prefs=read_ai_preferences(self.root)
        previous_text=self.text_model.currentText() or prefs['model']
        previous_vision=self.vision_model.currentText() or prefs['vision_model']
        try:
            models=installed_models(timeout=5)
            if not models:
                raise RuntimeError('Aucun modèle installé.')
            self.text_model.clear();self.vision_model.clear()
            self.text_model.addItems(models);self.vision_model.addItems(models)
            # Display installed choices only; text/vision labels indicate purpose, not capability guarantee.
            for box, preferred in ((self.text_model,previous_text),(self.vision_model,previous_vision)):
                index=box.findText(preferred)
                if index<0:
                    index=next((i for i in range(box.count()) if
                                ('vl' in box.itemText(i).lower() or 'llava' in box.itemText(i).lower()) == (box is self.vision_model)),0)
                box.setCurrentIndex(max(index,0))
            self.status.setText(f'{len(models)} modèles détectés dans Ollama.')
        except Exception as exc:
            self.status.setText('Connexion indisponible — lance « ollama serve ».')
            self.log.appendPlainText('❌ '+str(exc))

    def save(self):
        try:
            save_ai_preferences(self.root,self.text_model.currentText(),self.vision_model.currentText())
            self.status.setText('✅ Choix sauvegardés pour STEM+ et Auto Mix.')
        except Exception as exc:
            QMessageBox.warning(self,'Save settings',str(exc))

    def start_test(self, target):
        if self._thread is not None:return
        model=self.text_model.currentText() if target=='text' else self.vision_model.currentText()
        self.status.setText(f'Test {target} en cours…')
        self.progress.setVisible(True);self.progress.setRange(0,0) # busy animation, not a fake percent
        for b in (self.refresh_btn,self.server_btn,self.text_btn,self.vision_btn,self.save_btn):b.setEnabled(False)
        thread=QThread(self);worker=_TestWorker(target,model);worker.moveToThread(thread)
        self._thread=thread;self._worker=worker
        thread.started.connect(worker.run)
        worker.finished.connect(self._test_done)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._test_cleanup)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    @Slot(str,str,str)
    def _test_done(self, target, message, error):
        line=(f'❌ {target}: {error}' if error else f'✅ {target}: {message}')
        self.log.appendPlainText(line)
        self.status.setText(line[:180])

    @Slot()
    def _test_cleanup(self):
        self._thread=None;self._worker=None
        self.progress.setVisible(False)
        for b in (self.refresh_btn,self.server_btn,self.text_btn,self.vision_btn,self.save_btn):b.setEnabled(True)

    def reject(self):
        if self._thread is not None:
            self.status.setText('Le test termine son exécution avant la fermeture.')
            return
        super().reject()

    def accept(self):
        if self._thread is not None:
            self.status.setText('Le test termine son exécution avant la fermeture.')
            return
        super().accept()
