"""Edit VST3 normalized parameter overrides read from the JUCE host.

This intentionally does not pretend to be a native plugin editor: some VST3
controls are not exposed to host automation, and raw values are normalized.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QWidget, QFormLayout, QDoubleSpinBox, QPushButton, QDialogButtonBox)


from .plugin_parameters import parse_parameter_overrides

class ParameterEditorDialog(QDialog):
    def __init__(self, plugin_name, parameters, overrides, parent=None):
        super().__init__(parent)
        self.setWindowTitle('VST3 Parameters — ' + plugin_name)
        self.resize(730, 620)
        self._fields = {}
        self._defaults = {}
        self._overrides = dict(parse_parameter_overrides(overrides))
        layout = QVBoxLayout(self)
        note = QLabel('Only automatable parameters are shown. Values are normalized (0–1), not Hz or dB. '
                      'Edits apply on the NEXT offline FX preparation, not live.')
        note.setWordWrap(True); layout.addWidget(note)
        search = QLineEdit();search.setPlaceholderText('Filter parameters by name...');layout.addWidget(search)
        scroll = QScrollArea();scroll.setWidgetResizable(True)
        panel = QWidget(); self.form = QFormLayout(panel);scroll.setWidget(panel);layout.addWidget(scroll,1)
        for p in parameters:
            if not p.get('automatable',False):continue
            name = str(p.get('name',''))
            if name in ('MIDI CC','Internal') or not name.strip(): continue
            idx = p.get('index')
            if type(idx) is not int or idx < 0:continue
            value = float(p.get('value',0.0))
            self._defaults[idx] = min(1.0,max(0.0,value))
            spin = QDoubleSpinBox();spin.setRange(0,1);spin.setDecimals(5);spin.setSingleStep(0.01)
            spin.setValue(self._overrides.get(idx,self._defaults[idx]))
            caption = QLabel(f'{name}  [{idx}]  •  current: {p.get("text", "") or "?"}')
            caption.setToolTip('Parameter display text comes from initial plugin state; it may not update as you edit.')
            reset = QPushButton('Reset');reset.setMaximumWidth(65)
            reset.clicked.connect(lambda checked=False, i=idx: self._reset(i))
            row = QWidget(); horizontal=QHBoxLayout(row);horizontal.setContentsMargins(0,0,0,0)
            horizontal.addWidget(spin); horizontal.addWidget(reset)
            self.form.addRow(caption,row)
            self._fields[idx] = (spin,caption,row)
        search.textChanged.connect(self.filter_rows)
        layout.addWidget(QLabel('Reset returns a control to its initial inspected value. Use Clear overrides to remove all stored changes.'))
        actions=QHBoxLayout();clear=QPushButton('Clear overrides');clear.clicked.connect(self.clear_all);actions.addWidget(clear)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);actions.addWidget(buttons);layout.addLayout(actions)
        self._clear_all=False
        for spin,_,_ in self._fields.values():
            spin.valueChanged.connect(self._on_manual_edit)

    def _on_manual_edit(self, *_):
        self._clear_all=False

    def filter_rows(self,query):
        q=query.strip().casefold()
        for spin,label,row in self._fields.values():
            visible=q in label.text().casefold()
            label.setVisible(visible);row.setVisible(visible)

    def _reset(self,index):
        self._fields[index][0].setValue(self._defaults[index])

    def clear_all(self):
        for idx in self._fields:self._reset(idx)
        self._clear_all=True

    def overrides(self):
        if self._clear_all:
            return []
        edits=[]
        for idx,(spin,_,_) in self._fields.items():
            value=spin.value()
            if abs(value-self._defaults[idx])>0.00001:
                edits.append({'index':idx,'value':value})
        # Keep existing overrides on hidden/nonautomatable parameters unchanged.
        # Validation of new entries happens before rendering.
        for idx,val in self._overrides.items():
            if idx not in self._fields: edits.append({'index':idx,'value':val})
        return sorted(edits,key=lambda x:x['index'])
