"""First-run VST selection and role mapping, independent of audio rendering."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import QDialog, QVBoxLayout, QGridLayout, QComboBox, QLabel, QPushButton, QHBoxLayout, QMessageBox
from .plugin_registry import ROLES, default_scan_dirs, discover_plugins, suggested_roles, read_settings, save_settings

class PluginSetupDialog(QDialog):
    def __init__(self, settings_path:Path, parent=None):
        super().__init__(parent)
        self.settings_path=settings_path
        self.setWindowTitle('AI Mastering Lab — VST3 Setup')
        self.resize(700,390)
        self.plugins=[]
        root=QVBoxLayout(self)
        title=QLabel('VST3 PLUGIN SETUP');title.setStyleSheet('font-size:19px;font-weight:bold;');root.addWidget(title)
        intro=QLabel('Choisis tes plugins installés pour chaque rôle. Les suggestions reposent sur les noms, pas sur un test de compatibilité. Seul Pro-Q 4 est actuellement contrôlable automatiquement.')
        intro.setWordWrap(True);root.addWidget(intro)
        grid=QGridLayout();root.addLayout(grid)
        self.combos={}
        for row,(role,display) in enumerate(ROLES.items()):
            grid.addWidget(QLabel(display),row,0)
            combo=QComboBox();combo.setMinimumWidth(440);grid.addWidget(combo,row,1);self.combos[role]=combo
        self.status=QLabel('Recherche des VST3...');self.status.setWordWrap(True);root.addWidget(self.status)
        actions=QHBoxLayout()
        scan=QPushButton('↻ Rescan VST3');scan.clicked.connect(self.scan);actions.addWidget(scan)
        actions.addStretch()
        cancel=QPushButton('Cancel');cancel.clicked.connect(self.reject);actions.addWidget(cancel)
        ok=QPushButton('Save plugin preferences');ok.clicked.connect(self.save);actions.addWidget(ok)
        root.addLayout(actions)
        self.scan()

    def scan(self):
        saved=read_settings(self.settings_path).get('roles',{})
        selected={role:combo.currentData() or saved.get(role,'') for role,combo in self.combos.items()}
        self.plugins=discover_plugins(default_scan_dirs())
        suggestions=suggested_roles(self.plugins)
        for role,combo in self.combos.items():
            combo.clear();combo.addItem('None / decide later','')
            for p in self.plugins:combo.addItem(p['name']+'  —  '+p['path'],p['path'])
            preferred=selected.get(role) or suggestions.get(role,'')
            index=combo.findData(preferred)
            combo.setCurrentIndex(index if index>=0 else 0)
        self.status.setText(f'{len(self.plugins)} VST3 trouvés. Aucun plugin n’a été exécuté pendant le scan.')

    def save(self):
        mapping={role:(combo.currentData() or '') for role,combo in self.combos.items()}
        try:save_settings(self.settings_path,mapping)
        except Exception as exc:QMessageBox.critical(self,'Save failed',str(exc));return
        self.accept()
