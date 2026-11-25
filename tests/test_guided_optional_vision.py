import ast
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'src'/'mastering_lab'
def test_syntax():
    for f in ('mix_compare_ui.py','spectral_vision.py','version.py'):
        ast.parse((root/f).read_text(encoding='utf-8'))
def test_auto_vision_opt_in():
    code=(root/'mix_compare_ui.py').read_text(encoding='utf-8')
    assert 'self._auto_vision_optin.setChecked(False)' in code
    assert 'use_vision=self._auto_vision_optin.isChecked()' in code
def test_one_vision_request():
    code=(root/'spectral_vision.py').read_text(encoding='utf-8')
    assert code.count('response = transport(endpoint, payload, timeout)') == 1
    assert 'retry_payload' not in code
def test_version():
    assert "APP_VERSION = '0.11.6'" in (root/'version.py').read_text()
