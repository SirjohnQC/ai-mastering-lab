import ast
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'src/mastering_lab/stem_plus_ui.py').read_text(encoding='utf-8')
def test_syntax():
    ast.parse(SRC)
    ast.parse((ROOT/'scripts/stem_fx_prepare.py').read_text(encoding='utf-8'))
def test_restore():
    assert '_restore_previous_selection' in SRC
    assert '_remember_selection' in SRC
    assert 'QSettings' in SRC
    assert "actual != expected" in SRC
    assert "config = selection_config(files)" in SRC
def test_error_report():
    assert "if not script.is_file()" in SRC
    assert "QMessageBox.warning(self, 'Traitement audio impossible'" in SRC
    assert "def _parse_job_result" in SRC
def test_version():
    spec=importlib.util.spec_from_file_location('aml_version',ROOT/'src/mastering_lab/version.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    assert m.APP_VERSION=='0.10.2'
def test_script_present():
    assert (ROOT/'scripts/stem_fx_prepare.py').is_file()
